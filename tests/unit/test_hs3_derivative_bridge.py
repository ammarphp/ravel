"""Real portable public admission and mocked native-state boundary controls.

The fixtures are deliberately synthetic and never loaded/compiled. No ROOT
import, numerical runtime qualification or scientific review vote occurs here.
"""
from copy import deepcopy
import importlib.util
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from ravel.physics import hs3_likelihood as h,hs3_native as n
from ravel.workflow import science

def graph_document():
    return {'metadata':{'hs3_version':'0.2'},
      'distributions':[{'name':'model','type':'histfactory_dist','axes':[{'name':'x','edges':[0,1,2]}],
        'samples':[{'name':'signal','data':{'contents':[2,3]},'modifiers':[{'name':'mu','parameter':'mu','type':'normfactor'},
          {'name':'alpha','parameter':'alpha','type':'normsys','data':{'lo':.8,'hi':1.2},'constraint_name':'alpha_constraint'}]},
          {'name':'background','data':{'contents':[10,20]},'modifiers':[]}]},
        {'name':'alpha_constraint','type':'gaussian_dist','x':'alpha','mean':'nom','sigma':1.}],
      'data':[{'name':'obsData','type':'binned','axes':[{'name':'x','edges':[0,1,2]}],'contents':[12,23]}],
      'domains':[{'name':'default_domain','type':'product_domain','axes':[{'name':'mu','min':0.,'max':10.},{'name':'alpha','min':-2.,'max':2.},{'name':'x','edges':[0,1,2]}]},
        {'name':'selected','type':'product_domain','axes':[{'name':'mu','min':0.,'max':5.},{'name':'alpha','min':-1.,'max':1.}]}],
      'parameter_points':[{'name':'default_values','parameters':[{'name':'mu','value':1.},{'name':'alpha','value':0.},{'name':'nom','value':0.,'const':True},{'name':'x','value':.5}]}],
      'likelihoods':[{'name':'likelihood','distributions':['model'],'data':['obsData'],'aux_distributions':['alpha_constraint']}],
      'analyses':[{'name':'analysis','likelihood':'likelihood','domains':['selected'],'parameters_of_interest':['mu']}],
      'misc':{'ROOT_internal':{'ModelConfigs':{'analysis':{'mcName':'ModelConfig','pdfName':'model'}}}}}

class Var:
    def __init__(self,name,value,constant=False):self.name,self.value,self.constant=name,value,constant
    def GetName(self):return self.name
    def getVal(self):return self.value
    def setVal(self,value):self.value=value
    def isConstant(self):return self.constant
    def setConstant(self,value):self.constant=value
    def getMin(self,*_):return -10.
    def getMax(self,*_):return 10.

class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.base=Path(self.tmp.name).resolve()
        self.raw=graph_document();self.model=self.base/'original.json';self.model.write_text(json.dumps(self.raw))
        self.binary=self.base/'python';self.binary.write_text('#!/bin/sh\nexit 99\n');self.binary.chmod(0o755)
        artifact=self.base/'synthetic-ABI';artifact.write_text('Portable admission only, never loaded')
        provenance=self.base/'provenance.json';provenance.write_text('{"synthetic":true}')
        self.sources=[]
        for name,text in {'JSONFactories_HistFactory.cxx':'registerImporter<Synthetic>("histfactory_dist",true);',
             'JSONFactories_RooFitCore.cxx':'registerImporter<Synthetic>("gaussian_dist",true);',
             'RooFitHS3_wsfactoryexpressions.cxx':'R"({"sum": {}})"',
             'RooJSONFactoryWSTool.cxx':'// Never compiled','Domains.cxx':'// Never compiled','ModelConfig.cxx':'// Never compiled'}.items():
            p=self.base/name;p.write_text(text);self.sources.append(p)
        pin=lambda p:{'path':str(p),'sha256':h.digest(p)}
        self.config={'schema_version':1,'source':'Synthetic portable derivative admission only','max_seconds':10,
            'model':pin(self.model),'provenance':[pin(provenance)],
            'selection':{'analysis':'analysis','parameter_point':'default_values','points':[{'id':'mu1','parameters':{'mu':1.}}]},
            'derivatives':{'axes':[{'name':'mu','step':.5},{'name':'alpha','step':.25}],'max_points':256},
            'nll':{'extended':True,'offset':False,'eval_backend':'legacy','num_cpu':1,'constraints':'all_pdf_parameters','global_observables_source':'model'},
            'runtime':{'python':pin(self.binary),'artifacts':[pin(artifact)],'importer_sources':[pin(p) for p in self.sources],
                'modules':{'ROOT':pin(artifact),'cppyy':pin(artifact)},
                'loaded_libraries':{key:pin(artifact) for key in ['libCore','libRooFitCore','libRooFitHS3','libHistFactory']},
                'environment':{'PATH':'/usr/bin:/bin','LC_CTYPE':'C','PYTHONCOERCECLOCALE':'0','PYTHONDONTWRITEBYTECODE':'1','PYTHONNOUSERSITE':'1'},
                'root_version':'6.40.04','importer_config':{'allowExportInvalidNames':False,'allowSanitizeNames':False,'importNoDomainParametersAsRooConstVars':True}}}
        self.cp=self.base/'configuration.json';self.cp.write_text(json.dumps(self.config))
        self.graph=h.inspect_graph(self.model.read_bytes(),['histfactory_dist','gaussian_dist'])

    def test_source_anchor_domains_and_complete_state(self):
        points,plan=h.configured_points(self.config,self.graph,self.base)
        self.assertEqual(plan['parameter_order'],['mu','alpha','nom','x'])
        self.assertEqual([p['role'] for p in plan['request']['parameters']],['poi','nuisance','fixed','observable'])
        self.assertEqual(plan['request']['parameters'][0]['bounds'],{'min':0.,'max':5.})
        self.assertEqual(plan['request']['parameters'][1]['bounds'],{'min':-1.,'max':1.})
        self.assertEqual(plan['request']['parameters'][3]['bounds'],{'min':0,'max':2})
        self.assertTrue(all(p['values']['nom']==0 and p['constants']['nom'] and p['values']['x']==.5 for p in points))
        self.assertEqual(plan['identity']['model_sha256'],h.digest(self.model))

    def test_default_point_contract_unchanged_without_opt_in(self):
        config=deepcopy(self.config);config.pop('derivatives')
        rows,plan=h.configured_points(config,self.graph,self.base)
        self.assertIsNone(plan);self.assertEqual(rows,h.evaluation_points(self.graph,config['selection']))
        self.cp.write_text(json.dumps(config));inputs=h.inputs({'input':str(self.cp)},self.base)
        self.assertNotIn(Path(h.__file__).with_name('native_likelihood_derivatives.py'),inputs)

    def test_multiple_anchors_do_not_silently_select_one(self):
        c=deepcopy(self.config);c['selection']['points'].append({'id':'unused','parameters':{'mu':2.}})
        with self.assertRaisesRegex(ValueError,'exactly one'):h.configured_points(c,self.graph,self.base)

    def test_constant_data_and_unknown_axes_refuse(self):
        for name in ['nom','x','unrelated']:
            c=deepcopy(self.config);c['derivatives']['axes']=[{'name':name,'step':.1}]
            with self.subTest(name=name),self.assertRaises(ValueError):h.configured_points(c,self.graph,self.base)

    def test_staged_contract_regenerates_the_exact_original_plan(self):
        _,plan=h.configured_points(self.config,self.graph,self.base)
        out=self.base/'staged';out.mkdir()
        for source,destination in [(Path(h.__file__),'hs3_contract.py'),(Path(n.__file__),'native_worker.py'),(Path(h.__file__).with_name('native_likelihood_derivatives.py'),'native_likelihood_derivatives.py')]:
            shutil.copyfile(source,out/destination)
        spec=importlib.util.spec_from_file_location('synthetic_staged_hs3_contract',out/'hs3_contract.py');staged=importlib.util.module_from_spec(spec);spec.loader.exec_module(staged)
        points,replayed=staged.configured_points(self.config,self.graph)
        self.assertEqual(replayed,plan);self.assertEqual(points,h.configured_points(self.config,self.graph,self.base)[0])
        # A producer-resealed harmless kernel newline changes execution identity.
        with (out/'native_likelihood_derivatives.py').open('a') as f:f.write('\n')
        self.assertNotEqual(staged.configured_points(self.config,self.graph)[1],plan)

    def test_runtime_selection_and_nll_definition_have_distinct_pins(self):
        _,plan=h.configured_points(self.config,self.graph,self.base)
        c=deepcopy(self.config);c['runtime']['environment']['OMP_NUM_THREADS']='1'
        other=h.configured_points(c,self.graph,self.base)[1]
        self.assertNotEqual(plan['identity']['runtime_binding_sha256'],other['identity']['runtime_binding_sha256'])
        self.assertEqual(plan['identity']['evaluation_definition_sha256'],other['identity']['evaluation_definition_sha256'])
        c=deepcopy(self.config);c['selection']['points'][0]['parameters']['mu']=2.
        self.assertNotEqual(plan['identity']['evaluation_definition_sha256'],h.configured_points(c,self.graph,self.base)[1]['identity']['evaluation_definition_sha256'])

    def test_native_role_guard_refuses_implicit_global_and_unrelated(self):
        _,plan=h.configured_points(self.config,self.graph,self.base);vs={p['name']:Var(p['name'],p['value'],p['constant']) for p in plan['request']['parameters']}
        ws=SimpleNamespace(var=lambda name:vs.get(name))
        def mc(pois,nuisances,globals_=[],observables=[]):
            return SimpleNamespace(GetParametersOfInterest=lambda:[vs[x] for x in pois],GetNuisanceParameters=lambda:[vs[x] for x in nuisances],
                GetGlobalObservables=lambda:[vs[x] for x in globals_],GetConditionalObservables=lambda:[],GetObservables=lambda:[vs[x] for x in observables])
        n.check_derivative_axes(ws,mc(['mu'],['alpha']),plan)
        for configuration in [mc(['mu'],[],[]),mc(['mu'],['alpha'],['alpha']),mc(['mu'],['alpha'],[],['alpha'])]:
            with self.assertRaisesRegex(ValueError,'actual continuous'):n.check_derivative_axes(ws,configuration,plan)

    def test_existing_evaluator_full_reset_and_reduction(self):
        points,plan=h.configured_points(self.config,self.graph,self.base)
        vs={p['name']:Var(p['name'],p['value'],p['constant']) for p in plan['request']['parameters']};vs['native_implicit']=Var('native_implicit',3.,True)
        class Nll:
            def getVal(self):
                mu,alpha=vs['mu'].value,vs['alpha'].value
                result=mu*mu+2*mu*alpha+3*alpha*alpha+vs['native_implicit'].value
                vs['native_implicit'].value=999.
                return result
        mock_ROOT=SimpleNamespace(ravel_hs3_v1=SimpleNamespace(nll=lambda *_:Nll()),SetOwnership=lambda *_:None)
        ws=SimpleNamespace(allVars=lambda:list(vs.values()),var=lambda name:vs.get(name),arg=lambda name:vs.get(name))
        rows=n.evaluate(mock_ROOT,ws,None,None,{'points':points})
        observations=h.derivative_observations({'evaluations':rows},plan)
        result=h.derivative_kernel().reduce_observations(plan,observations)
        self.assertEqual(result['levels'][0]['gradient'],[2.,2.]);self.assertEqual(result['levels'][0]['hessian'],[[2.,2.],[2.,6.]])
        self.assertEqual(rows[0]['nll'],4.);self.assertTrue(all(len(r['parameters'])==5 for r in rows))
        rows[0]['source_assignments']['nom']['constant']=False
        with self.assertRaisesRegex(ValueError,'constant state'):h.derivative_observations({'evaluations':rows},plan)

    def test_actual_public_plan_binds_kernel_and_rejects_stale_source(self):
        policy={'schema_version':1,'actors':{'proposer':'producer','executor':'producer','physics_critic':'critic','skeptical_verifier':'verifier','physics_decider':'decider'},
                'max_redos':0,'allowed_changed_paths':[],'allowed_stages':['science'],'required_checks':[{'id':'identity','kind':'integrity'},{'id':'native_graph','kind':'scientific'}],
                'claim_scopes':{'diagnostic':{'checks':['identity','native_graph'],'actions':['delivery','reuse']}}}
        spec={'schema_version':2,'mode':'hs3-likelihood','source':'Synthetic derivative planning only, never native execution','assumptions':['No native execution or approval.'],
              'max_seconds':20,'max_attempts':1,'approval_mode':'scripted_yes','task':{'input':str(self.cp)},
              'review_policy':{'schema_version':1,'policy':policy,'correction_contract':{'task_fields':[],'input_slots':[]}}}
        source=self.base/'science.json';source.write_text(json.dumps(spec));run=self.base/'study'
        plan=science.plan(run,source);verified=science.verify_plan(run)
        self.assertEqual(plan['stage_binding']['fingerprint'],verified['stage_binding']['fingerprint'])
        expected=h.inputs({'input':str(self.cp)},self.base)
        self.assertIn(Path(h.__file__).with_name('native_likelihood_derivatives.py'),expected)
        self.assertFalse((run/'inputs/science-approval.json').exists());self.assertFalse((run/'execution_state.json').exists())
        with self.model.open('a') as f:f.write('\n')
        with self.assertRaisesRegex(ValueError,'changed HS3'):science.verify_plan(run)

    def mock_native_process(self,corrupt_kernel=False):
        """Explicit synthetic delivery; never start a process or import ROOT."""
        def deliver(argv,*,cwd,env,stdout,stderr,timeout,check):
            out=Path(cwd);request=h.document(Path(argv[-1]).read_bytes());runtime=request['configuration']['runtime']
            self.assertEqual(env,runtime['environment']);self.assertGreater(timeout,0)
            staged_spec=importlib.util.spec_from_file_location('mock_staged_contract',out/'hs3_contract.py');staged=importlib.util.module_from_spec(staged_spec);staged_spec.loader.exec_module(staged)
            graph=staged.inspect_graph((out/'original-hs3.json').read_bytes(),request['supported_types'])
            _,plan=staged.configured_points(request['configuration'],graph)
            self.assertEqual(plan,request['derivative_plan'])
            rows=[]
            for point in request['points']:
                mu,alpha=point['values']['mu'],point['values']['alpha']
                rows.append({'id':point['id'],'nll':mu*mu+2*mu*alpha+3*alpha*alpha,
                    'source_overrides':point['overrides'],'source_assignments':{name:{'value':v,'constant':point['constants'][name]} for name,v in point['values'].items()}})
            for row in rows:row['delta_nll_from_first']=row['nll']-rows[0]['nll']
            phase={'root_version':runtime['root_version'],'modules':runtime['modules'],'required_loaded_images':runtime['loaded_libraries'],
                   'environment':runtime['environment'],'cwd':str(out),'python':runtime['python']}
            native={'status':'passed','model_sha256':request['model_sha256'],'binding':request['binding'],'root_version':runtime['root_version'],
                    'source_export_metadata':request['inventory']['hs3_metadata'],'nll_options':request['configuration']['nll'],
                    'native_helper_sha256':hashlib.sha256(n.HELPER.encode()).hexdigest(),'runtime_before':phase,'runtime_after':phase,'evaluations':rows,
                    'derivative_plan_sha256':plan['plan_sha256'],'workspace_inventory':{'model_config':{'parameters_of_interest':['mu'],'nuisance_parameters':['alpha'],
                        'global_observables':['nom'],'conditional_observables':[],'observables':['x']}}}
            (out/'native-evaluation.json').write_text(json.dumps(native))
            for name in ['native-roundtrip-hs3.json','imported-workspace-inventory.json']:(out/name).write_text('{"synthetic":true}')
            (out/'imported-workspace.root').write_bytes(b'SYNTHETIC UNIT FIXTURE, NOT ROOT')
            if corrupt_kernel:
                with (out/'native_likelihood_derivatives.py').open('a') as f:f.write('\n')
            return SimpleNamespace(returncode=0)
        return deliver

    def test_existing_run_emits_complete_stencil_observations_and_estimates(self):
        out=self.base/'mock-output'
        with patch.object(h.subprocess,'run',self.mock_native_process()):
            result=h.run({'input':str(self.cp)},self.base,out)
        self.assertEqual(result['status'],'passed');self.assertFalse(result['physics_validated'])
        plan=h.document((out/'derivative-plan.json').read_bytes());obs=h.document((out/'derivative-observations.json').read_bytes())
        self.assertEqual(len(plan['points']),len(obs['rows']));self.assertEqual(result['derivatives']['levels'][0]['hessian'],[[2.,2.],[2.,6.]])
        self.assertFalse(result['derivatives']['covariance_qualified']);self.assertTrue((out/'native_likelihood_derivatives.py').is_file())

    def test_staged_kernel_drift_refuses_before_derivative_output(self):
        out=self.base/'mock-drift-output'
        with patch.object(h.subprocess,'run',self.mock_native_process(corrupt_kernel=True)):
            result=h.run({'input':str(self.cp)},self.base,out)
        self.assertEqual(result['status'],'failed');self.assertIn('staged derivative kernel drift',result['error']['message'])
        self.assertFalse((out/'derivative-estimates.json').exists());self.assertTrue((out/'native-evaluation.json').exists())

if __name__=='__main__':unittest.main()
