"""Pure metadata/mark algebra and mocked consumer transport; no engine jobs."""
import ast
from copy import deepcopy
from fractions import Fraction
import hashlib
import inspect
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from ravel.physics import marked_joint_analysis as a, joint_analytic as ja, mc_auxiliary as mc
from ravel.physics.normalized_profile_domain import relative_denominator_domain as domain
from ravel.physics.joint_profile import WorkBudget
from ravel.workflow import science


def fixture():
    source={'active_parameter_names':['shape','fixed'], 'active_parameter_domains':{
        'shape':{'initial':0.,'bounds':[-1.,1.],'fixed':False},
        'fixed':{'initial':2.,'bounds':[0.,3.],'fixed':True}}}
    classes=[{'id':'positive','initial':.5,'contribution':[1],'denominator_mark':1,'exposure':None},
             {'id':'negative','initial':.5,'contribution':[-1],'denominator_mark':1,'exposure':None}]
    model={'classes':classes,'bins':[{'id':'signal'}],'mc_design':{'kind':'fixed_n_categories','total_groups':4}}
    case={'id':'supplied','workspace':{},'measurement':'measurement','background_policy':'separable_signal_mc','background_source':None,
          'MC':{},'response':{},'configuration':{},'signal_samples':{},'source_bin_map':[],
          'mu_domain':{'initial':1,'upper':20},'source_bound_semantics':{n:{'lower':'numerical','upper':'numerical'} for n in source['active_parameter_names']},
          'data':None,'requests':[{'id':'comparison','kind':'finite_mc_comparison','strengths':[1],
              'fixed_source':{},'fixed_latent':{'positive':.25,'negative':.75}}]}
    limits={'execution_seconds':300,'fit_budget':{'objective_calls':100,'gradient_calls':100,'feasibility_lp_calls':10,'stationarity_lp_calls':10,'maxiter':50,'lp_maxiter':50,'wall_seconds':60},
            'maximum_free_coordinates':30,'capture_bytes':1<<20,'result_bytes':1<<20,'journal_bytes':1<<20}
    doc={'schema_version':1,'model_id':'mock-consumer','assumptions':['supplied marked law','independent experiments'],'limits':limits,'cases':[case]}
    return doc,case,source,model


class StatisticsConsumerTests(unittest.TestCase):
    def test_scale_invariance_including_signed_marks(self):
        for scale in (1e-200,1.,1e200):
            row=domain([-2*scale,scale,4*scale],denominator_floor=1e-10)['denominator_row']
            self.assertEqual(row,[-.5,.25,1.]);self.assertEqual(sum(Fraction(x)*p for x,p in zip(row,[Fraction(1,4),Fraction(1,4),Fraction(1,2)])),Fraction(7,16))

    def test_relative_floor_boundary_and_lost_mark_refusal(self):
        r=domain([0,1],denominator_floor=.125)['denominator_row']
        self.assertEqual(r[1]*.125-.125,0)
        self.assertLess(r[1]*math.nextafter(.125,0)-.125,0)
        with self.assertRaisesRegex(ValueError,'loses'):domain([1e308,1e-308],denominator_floor=1e-10)
        for x in ([0,0],[True,1],[-1,0],[float('nan'),1]):
            with self.assertRaises(ValueError):domain(x,denominator_floor=1e-10)

    def test_auxiliary_population_does_not_impose_reference_signal_positivity(self):
        _,_,_,model=fixture();latent={'positive':.25,'negative':.75}
        with self.assertRaisesRegex(ValueError,'NET'):mc._physical(model,latent)
        self.assertEqual(mc.complete_auxiliary_means(model,latent),{'mc_means':[1.,3.]})
        self.assertEqual(latent,{'positive':.25,'negative':.75})
        for p in ({'positive':.2,'negative':.7},{'positive':-1,'negative':2},{'positive':1}):
            with self.assertRaises(ValueError):mc.complete_auxiliary_means(model,p)

    def test_actual_constraint_assembly_removes_only_reference_rows(self):
        # Execute only actual linear-assembly statements, with supplied arrays;
        # never execute fit/evaluation/LP/minimize.
        tree=ast.parse(inspect.getsource(ja)); cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='AnalyticJointProfiler')
        fn=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='fit')
        begin=next(i for i,n in enumerate(fn.body) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='W' for t in n.targets))
        end=next(i for i,n in enumerate(fn.body) if isinstance(n,ast.FunctionDef) and n.name=='parameters')
        code=compile(ast.fix_missing_locations(ast.Module(body=fn.body[begin:end],type_ignores=[])),'<actual linear assembly>','exec')
        from types import SimpleNamespace as NS
        classes=[{'contribution':[1.],'denominator_mark':1e-200},{'contribution':[-1.],'denominator_mark':1e-200}]
        def run(provider):
            env={'np':np,'relative_denominator_domain':domain,'classes':classes,'T':np.array([[1.],[-1.]]),'constant':np.array([0.,1.]),'fixed_n':True,
                 'floor':1e-10,'fixed_latent':None,'counts':[1,1],'dimension':1,'self':NS(_joint=NS(_provider=provider),_mc_document={'bins':[{'id':'x'}]})}
            exec(code,env);return env
        new=run(object());old=run(None)
        self.assertEqual([l['kind'] for l in new['labels']],['denominator_floor','last_probability_lower','last_probability_upper'])
        self.assertEqual(old['labels'][0]['kind'],'net')
        self.assertAlmostEqual(new['h'][0],1-1e-10)
        # At p=(.25,.75), old reference signal is -.5; transported signal
        # may instead place the negative category outside and be +.25.
        self.assertLess((old['G']@np.array([.25])+old['h'])[0],0)
        self.assertTrue(np.all(new['G']@np.array([.25])+new['h']>=0))

    def test_actual_signed_transport_has_valid_signal_but_invalid_reference_net(self):
        from ravel.physics.marked_response_provider import mark_jet
        d={'schema_version':1,'category_ids':['positive','negative'],'destination_ids':['signal','outside'],'fitted_destinations':['signal'],
           'axes':[{'name':'t','knots':[0,1]}],'reference_point':{'t':0},'category_weights':[1,-1],'denominator_marks':[1,1],
           'scale':1,'total_groups':4,'anchors':[{'point':[0],'allocation':[[1,0],[1,0]]},{'point':[1],'allocation':[[1,0],[0,1]]}],
           'provenance':{'category_partition':'fabricated complete groups','joint_anchor_identity':'same groups','interpolation':'new_piecewise_multilinear_fixed_mark_law','calibration':'none'}}
        jet=mark_jet(d,{'shape':1},{'positive':.25,'negative':.75},['shape'],{'t':'shape'},['signal'])
        self.assertEqual(jet['signal'],[.25]);self.assertEqual(jet['source_jacobian'],[[.75]])
        self.assertEqual(jet['latent_jacobian'],[[.75,-.25]])
        self.assertLess(.25-.75,0) # same source probabilities, different nuisance point

    def test_shared_covariance_actual_provider_method_preserves_cross_point_terms(self):
        from ravel.physics.marked_response_provider import MarkedResponseProvider
        provider=object.__new__(MarkedResponseProvider)
        provider._document={'schema_version':1,'category_ids':['A','U'],'destination_ids':['signal','outside'],'fitted_destinations':['signal'],
           'axes':[{'name':'t','knots':[0,1]}],'reference_point':{'t':0},'category_weights':[1,1],'denominator_marks':[1,1],
           'scale':2,'total_groups':4,'anchors':[{'point':[0],'allocation':[[0,1],[0,1]]},{'point':[1],'allocation':[[1,0],[0,1]]}],
           'provenance':{'category_partition':'fabricated complete groups','joint_anchor_identity':'same groups','interpolation':'new_piecewise_multilinear_fixed_mark_law','calibration':'none'}}
        provider._binding={'axis_to_source':{'t':'shape'}}
        with patch.object(provider,'assert_custody'):
            result=provider.shared_template_covariance([{'shape':.5},{'shape':1}],{'A':.25,'U':.75})
        self.assertEqual(result['scope'],'exact_fixed_N_linear_estimator_covariance')
        self.assertEqual(result['covariance'][0][2],.09375)
        self.assertEqual(result['covariance'][0][3],-.09375)
        self.assertFalse(result['likelihood_inferred'])

    def test_density_branch_uses_complete_auxiliary_not_reference_nominal(self):
        source=inspect.getsource(ja.AnalyticPublishedJoint._evaluate_with_gradient)
        self.assertIn('self._mc.nominal(latent) if self._provider is None else self._mc.auxiliary_means(latent)',source)
        fit=inspect.getsource(ja.AnalyticJointProfiler.fit)
        self.assertIn('else:self._mc.auxiliary_means(fixed_latent)',fit)

    def test_source_masks_fixed_flags_and_complete_semantics(self):
        doc,case,source,model=fixture();a.validate_requests(case,source,model)
        for mutation in ('fixed','unknown','bound','semantics','probability'):
            c=deepcopy(case)
            if mutation=='fixed':c['requests'][0]['fixed_source']={'fixed':1}
            if mutation=='unknown':c['requests'][0]['fixed_source']={'missing':0}
            if mutation=='bound':c['requests'][0]['fixed_source']={'shape':2}
            if mutation=='semantics':del c['source_bound_semantics']['fixed']
            if mutation=='probability':c['requests'][0]['fixed_latent']['negative']=.7
            with self.assertRaises(ValueError):a.validate_requests(c,source,model)

    def test_resource_population_and_explicit_long_fit_budget(self):
        doc,_,_,_=fixture();_,counts=a.prepare(doc)
        self.assertEqual(counts,{'fit_calls':4,'shape_density_calls':0,'shared_covariance_calls':0})
        with self.assertRaises(ValueError):WorkBudget(doc['limits']['fit_budget']) # legacy default30
        WorkBudget(doc['limits']['fit_budget'],maximum_wall_seconds=300)
        doc['limits']['execution_seconds']=239
        with self.assertRaises(ValueError):a.prepare(doc)
        doc['limits']['execution_seconds']=300;doc['limits']['fit_budget']['wall_seconds']=301
        with self.assertRaises(ValueError):a.prepare(doc)

    def test_contrast_preserves_raw_values_and_failure(self):
        f={'verified':True,'nll':10};c={'verified':True,'nll':9}; old=deepcopy(c)
        r=a.profile_contrast(f,c);self.assertEqual(r['raw_twice_delta_nll'],-2);self.assertFalse(r['passed']);self.assertEqual(c,old)
        c={'verified':False,'nll':10};self.assertIsNone(a.profile_contrast(f,c)['twice_delta_nll'])
        r=a.profile_contrast(f,{'verified':True,'nll':10-1e-7});self.assertEqual(r['twice_delta_nll'],0);self.assertLess(r['raw_twice_delta_nll'],0)
        self.assertFalse(a.profile_contrast(f,{'verified':True,'nll':float('nan')})['passed'])

    def test_ordinary_route_closed_discriminator_and_legacy(self):
        spec={'mode':'joint-fit','task':{'input':'x','response_family':a.FAMILY}}
        self.assertIs(science.adapter(spec),a);a.validate(spec['task'])
        self.assertEqual(science.adapter({'mode':'joint-fit','task':{'input':'x'}}).__name__,'ravel.physics.joint_fit')
        for task in ({'input':'x','response_family':'native-finite-difference'},{'input':'x','response_family':a.FAMILY,'clip':True}):
            with self.assertRaises(ValueError):a.validate(task)

    def _run_fake(self, temporary, *, fail=False, late=False, shape=False):
        temporary=str(Path(temporary).resolve())
        doc,case,source,model=fixture();calls=[];clock=[0.]
        if shape:
            case['requests']=[{'id':'shape','kind':'shape','mu':2,'latent':{'positive':.25,'negative':.75},'source_points':[{'shape':0,'fixed':2},{'shape':1,'fixed':2}]}]
        doc,counts=a.prepare(doc)
        class Joint:
            def contract(self):return {'source':'mock','auxiliaries_once':True}
            def evaluate_with_gradient(self,point,latent,**kw):
                calls.append(('shape',deepcopy(point),deepcopy(latent),kw));return {'finite':True,'nll':123.25,'coordinate_order':['mu','shape']}
        class Provider:
            def shared_template_covariance(self,points,latent):
                calls.append(('covariance',deepcopy(points),deepcopy(latent)))
                return {'basis':['all supplied destinations'],'covariance':[[4,2],[2,9]],'scope':'first_order_shared_denominator_delta_covariance','likelihood_inferred':False}
        class Profiler:
            def fit(self,**kw):
                calls.append(('fit',deepcopy({k:v for k,v in kw.items() if k!='wall_hook'})))
                if late:clock[0]=301
                return {'verified':not fail,'nll':100.25+(0 if kw['fixed_mu'] is None else 1),'parameters':{'latent':deepcopy(kw['fixed_latent'])},'attempts':[{'nll':101.25,'verified':False}]}
        with patch.object(a,'_capture',return_value=(doc,counts,{},[(case,{},object(),Path('response'),None)])),patch.object(a,'construct',return_value=(Joint(),Provider(),Profiler())),patch.object(a.time,'monotonic',side_effect=lambda:clock[0]):
            result=a.run({'input':'mock','response_family':a.FAMILY},temporary,Path(temporary)/'out')
        return result,calls,Path(temporary)/'out'

    def test_actual_consumer_four_fit_sequence_masks_raw_nll_and_no_rescaling(self):
        with tempfile.TemporaryDirectory() as tmp:
            result,calls,out=self._run_fake(tmp)
            self.assertEqual(result['status'],'passed');self.assertEqual(result['calls']['fits'],4)
            fits=[r[1] for r in calls if r[0]=='fit'];self.assertEqual([v['fixed_mu'] for v in fits],[None,1,None,1])
            self.assertEqual([v['fixed_latent'] for v in fits],[{'positive':.25,'negative':.75}]*2+[None,None])
            rows=result['cases'][0]['requests'][0]['fits'];self.assertEqual([r['result']['nll'] for r in rows],[100.25,101.25,100.25,101.25])
            journal=[json.loads(s) for s in (out/'marked-analysis.jsonl').read_text().splitlines()]
            previous=None
            for i,row in enumerate(journal):
                self.assertEqual((row['sequence'],row['previous_sha256']),(i,previous));previous=hashlib.sha256(a.compact(row)).hexdigest()
            self.assertEqual(result['journal']['head_sha256'],previous)

    def test_failed_fit_not_promoted_and_remaining_declared_fits_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            result,_,_=self._run_fake(tmp,fail=True)
            self.assertEqual(result['status'],'failed');self.assertEqual(result['calls']['fits'],4)
            self.assertTrue(all(r['result']['nll'] is not None for r in result['cases'][0]['requests'][0]['fits']))

    def test_late_budget_preserves_literal_return_before_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            result,_,out=self._run_fake(tmp,late=True)
            self.assertEqual(result['status'],'failed');self.assertEqual(result['error']['type'],'TimeoutError')
            rows=[json.loads(s) for s in (out/'marked-analysis.jsonl').read_text().splitlines()]
            self.assertEqual(rows[-1]['state'],'returned');self.assertEqual(rows[-1]['payload']['nll'],100.25)
            self.assertEqual(result['calls']['fits'],1)

    def test_shape_consumer_shared_covariance_not_auxiliary_constraint(self):
        with tempfile.TemporaryDirectory() as tmp:
            result,calls,_=self._run_fake(tmp,shape=True)
            self.assertEqual(result['status'],'passed');self.assertEqual(result['calls']['fits'],0)
            self.assertEqual([c[0] for c in calls],['shape','shape','covariance'])
            req=result['cases'][0]['requests'][0]
            self.assertEqual(req['template_covariance_mu1']['scope'],'first_order_shared_denominator_delta_covariance')
            self.assertEqual(req['points'][0]['raw']['nll'],123.25)
            self.assertFalse(req['template_covariance_mu1']['likelihood_inferred'])

    def test_source_capture_complete_ledger_and_opaque_source_without_compilation(self):
        from ravel.physics.marked_response_provider import category_mark_records
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary).resolve();doc,case,_,_=fixture()
            response={'schema_version':1,'category_ids':['A','B'],'destination_ids':['signal','outside'],'fitted_destinations':['signal'],
                'axes':[{'name':'t','knots':[0,1]}],'reference_point':{'t':0},'category_weights':[1,-1],'denominator_marks':[1,1],
                'scale':1,'total_groups':4,'anchors':[{'point':[0],'allocation':[[1,0],[1,0]]},{'point':[1],'allocation':[[1,0],[0,1]]}],
                'provenance':{'category_partition':'fabricated','joint_anchor_identity':'same groups','interpolation':'new_piecewise_multilinear_fixed_mark_law','calibration':'none'}}
            def write(name,value):
                p=root/name;p.write_bytes(a.compact(value) if not isinstance(value,bytes) else value)
                return {'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
            rp=write('response.json',response)
            classes=[{'id':name,'contribution':[weight],'denominator_mark':1,'exposure':None,'observed':count,
                      'observed_group_ids':[name+str(i) for i in range(count)],'initial':initial,'source':'response'}
                     for name,weight,count,initial in [('A',1,3,.75),('B',-1,1,.25)]]
            bins=[{'id':'signal','role':'signal','source':'response'}]
            design={'kind':'fixed_n_categories','sampling_law':'iid_fixed_mark_categories','fixed_marks':True,'support_complete':True,'ledger_source':'ledger',
                    'independence':'iid_groups_within_one_fixed_N_stream','total_groups':4,'kappa':1,'normalization_source':'response','normalization_meaning':'supplied conditional scale'}
            ledger={'schema_version':1,'sampling_law':design['sampling_law'],'support_complete':True,
                    'classes':[{k:c[k] for k in ('id','contribution','denominator_mark','exposure')} for c in classes],
                    'groups':[{'id':g,'class_id':c['id'],'contribution':c['contribution'],'denominator_mark':1} for c in classes for g in c['observed_group_ids']],
                    'normalization':{k:design[k] for k in ('total_groups','kappa','normalization_meaning')},'bins':[{'id':'signal','role':'signal'}]}
            records=category_mark_records(response);signatures={r['id']:hashlib.sha256(a.compact(r)).hexdigest() for r in records}
            groups={'schema_version':1,'sampling_unit':'same_complete_IID_generator_groups_at_all_anchors','category_marks':records,
                    'groups':[{'id':g,'class_id':c['id'],'category_mark_sha256':signatures[c['id']]} for c in classes for g in c['observed_group_ids']]}
            pins={'response':rp,'ledger':write('ledger.json',ledger),'group-marks':write('groups.json',groups),'source-note':write('source-note.bin',b'opaque\x00source')}
            model={'schema_version':2,'model_id':'complete-test','sources':[{'id':name,**pin,'reference':'artificial test source'} for name,pin in pins.items()],
                   'bins':bins,'mc_design':design,'classes':classes,'assumptions':['complete support','same fixed-N experiment']}
            workspace={'channels':[{'name':'c','samples':[{'name':'b','data':[10],'modifiers':[]},{'name':'s','data':[.5],'modifiers':[{'name':'mu','type':'normfactor','data':None}]}]}],
                       'observations':[{'name':'c','data':[10]}],'measurements':[{'name':'measurement','config':{'poi':'mu','parameters':[]}}],'version':'1.0.0'}
            case.update(workspace=write('workspace.json',workspace),MC=write('MC.json',model),response=rp,signal_samples={'c':['s']},source_bin_map=[{'channel':'c','bin':0,'mc_bin_id':'signal'}],
                        configuration={'axis_to_source':{'t':'shape'},'source_data_id':'response','group_ledger_source_id':'group-marks','sampling_independence':'supplied_source_and_new_MC_auxiliaries_independent'})
            case['requests'][0]['fixed_latent']={'A':.25,'B':.75}
            task={'input':write('input.json',doc)['path'],'response_family':a.FAMILY}
            captured=a._capture(task,root)
            self.assertEqual(len(captured[2]),7);self.assertEqual(captured[1]['fit_calls'],4)
            self.assertEqual(a.resource_bounds(task,root)['maximum_optimizer_attempts'],12)
            (root/'source-note.bin').write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'source changed'):a.inputs(task,root)

    def test_output_source_overlap_refuses_before_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc,case,_,_=fixture();out=Path(tmp)/'out';out.mkdir();inputpath=out/'source.json';inputpath.write_text('{}')
            _,counts=a.prepare(doc)
            with patch.object(a,'_capture',return_value=(doc,counts,{str(inputpath):b'{}'},[])):
                with self.assertRaises(ValueError):a.run({},tmp,out)
            self.assertEqual(list(out.iterdir()),[inputpath])


if __name__=='__main__':unittest.main()
