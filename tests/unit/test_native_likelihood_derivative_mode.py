"""Existing public input/command/admission route with a closed zero-fit opt-in."""
import ast
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import pytest
from ravel.physics import native_likelihood as n, native_likelihood_derivatives as d, combine_derivatives as c
from test_native_likelihood import fixture
from test_combine_derivatives import fixture as protocol_fixture, run as execute_mock


def config(tmp_path):
    cp,cfg,*rest=fixture(tmp_path)
    cfg['schema_version']=3
    cfg['runtime']['expected']['root_version']='6.30/00'
    cfg['fit'].update(method='MultiDimFit',points=None,fixed_witness_points=[])
    cfg['derivatives']={'anchor':{'r':1.},'axes':[{'name':'r','step':.25}],'max_points':32}
    cp.write_text(json.dumps(cfg))
    return cp,cfg,rest


def test_public_input_and_resource_observation_binds_all_three_implementations(tmp_path):
    cp,cfg,rest=config(tmp_path)
    paths=n.inputs({'input':str(cp)},tmp_path)
    assert paths[-3:]==[Path(n.__file__),Path(c.__file__),Path(d.__file__)]
    assert paths[:2]==[cp,rest[0]]
    assert n.execution_seconds({'input':str(cp)},tmp_path)==10
    from ravel.workflow import science
    assert science.task_inputs({'mode':'native-likelihood','task':{'input':str(cp)},'max_seconds':10},tmp_path)==paths


def test_native_derivative_commands_build_workspace_and_do_not_invoke_optimizer(tmp_path):
    cp,cfg,_=config(tmp_path);parsed=n._configuration({'input':str(cp)},tmp_path)
    build,fit=n.commands(cfg,parsed[3],tmp_path,has_response=True)
    assert fit is None
    assert build[1].endswith('source/card.txt')
    assert build[-2:]==['-P','ravel_source_response:model']


@pytest.mark.parametrize('mutate',[
    lambda cfg:cfg['fit'].update(points=5),lambda cfg:cfg['fit'].update(data='asimov_background'),
    lambda cfg:cfg['fit'].update(method='AsymptoticLimits'),lambda cfg:cfg['fit'].update(fixed_witness_points=['0']),
    lambda cfg:cfg['fit'].update(minimizer={'strategy':1,'tolerance':.01}),
    lambda cfg:cfg['derivatives'].update(max_points=257),lambda cfg:cfg['derivatives']['axes'][0].update(step=float('inf')),
    lambda cfg:cfg['derivatives']['axes'].append(deepcopy(cfg['derivatives']['axes'][0])),
    lambda cfg:cfg['derivatives']['anchor'].update(r=True),lambda cfg:cfg['derivatives'].update(optimizer='invented')])
def test_derivative_mode_is_closed_and_never_carries_fit_or_extra_calls(tmp_path,mutate):
    cp,cfg,_=config(tmp_path);mutate(cfg);cp.write_text(json.dumps(cfg))
    with pytest.raises(ValueError):n.inputs({'input':str(cp)},tmp_path)


def test_host_cross_checks_modelconfig_and_reduces_real_protocol_delivery():
    args=protocol_fixture();delivery=execute_mock(args)
    ws={k:delivery['definition']['initial_state']['model_config'][k] for k in ('pois','nuisances','observables','global_observables')}
    ws['data_entries']=2
    # Extraction consumes the ordinary model contract, including its optional source_graph branch.
    cfg={'derivatives':args[4],'model':{}};context=deepcopy(args[5]);context['definition']['declared_poi_domain']=args[6]
    # Regenerate under actual source context: changing context cannot inherit rows.
    args=list(args);args[5]=context;delivery=execute_mock(tuple(args))
    result=n._extract_derivatives({'workspace':ws,'derivatives':delivery},cfg,context,d)
    assert result['passed'] and result['fit_calls']==0 and not result['profiler_derivative_qualified']
    ws['nuisances']=[]
    with pytest.raises(ValueError,match='population differs'):n._extract_derivatives({'workspace':ws,'derivatives':delivery},cfg,context,d)


def test_generated_native_worker_calls_same_nll_and_closes_staged_source_guard():
    tree=ast.parse(n.NATIVE_PROBE)
    workspace=next(node for node in tree.body if isinstance(node,ast.If) and ast.unparse(node.test)=='len(sys.argv) > 2')
    calls=[node for node in ast.walk(workspace) if isinstance(node,ast.Call)]
    assert len([node for node in calls if isinstance(node.func,ast.Attribute) and node.func.attr=='createNLL'])==1
    # Calibration and fixed-state consumers also execute; identify the derivative consumer exactly.
    consumers=[node for node in calls if isinstance(node.func,ast.Attribute)
               and ast.unparse(node.func)=="modules['consumer'].execute"]
    assert len(consumers)==1
    execute=consumers[0]
    assert ast.unparse(execute.args[3])=='nll'
    assert not any(isinstance(node.func,ast.Attribute) and node.func.attr in ('fitTo','minimize','migrad','hesse') for node in calls)
    assert 'staged derivative implementation changed' in n.NATIVE_PROBE
    assert 'derivative workspace/worker changed' in n.NATIVE_PROBE


@pytest.mark.parametrize('failure',['success','late_exception','state_drift','nonfinite'])
def test_real_generated_worker_and_existing_host_dispatch_with_inert_root_protocol(tmp_path,monkeypatch,failure):
    """Execute generated Python bytes with inert objects; no ROOT or child process."""
    import contextlib
    import io
    import os
    import sys
    import types
    from test_combine_derivatives import fixture as inert_fixture
    from test_native_likelihood import VERSION_LOG
    cp,cfg,_=config(tmp_path)
    cfg['fit'].update(poi='mu',domain=['0','3'])
    cfg['derivatives']={'anchor':{'theta':.5},'axes':[{'name':'mu','step':.25},{'name':'theta','step':.125}],'max_points':256}
    cp.write_text(json.dumps(cfg))
    w,mc,data,nll,*_=inert_fixture()
    attempted=[]
    if failure!='success':
        original_get=nll.getVal
        def get():
            attempted.append(len(attempted)+1)
            value=original_get()
            if len(attempted)==2:
                if failure=='late_exception':raise RuntimeError('late generated-worker inert failure')
                if failure=='state_drift':w.var('nom').setVal(7.)
                if failure=='nonfinite':return float('inf')
            return value
        nll.getVal=get
    w.obj=lambda name:mc if name=='ModelConfig' else None
    w.data=lambda name:data if name=='data_obs' else None
    options=[]
    class LinkedList:
        def __init__(self):self.rows=[]
        def Add(self,row):self.rows.append(row)
    def create_nll(actual,linked):
        assert actual is data and isinstance(linked,LinkedList)
        options.extend(linked.rows)
        return nll
    mc.pdf.createNLL=create_nll
    class File:
        def Get(self,name):assert name=='w';return w
        def Close(self):pass
    root=types.ModuleType('ROOT')
    root.gROOT=SimpleNamespace(SetBatch=lambda x:None,GetVersion=lambda:cfg['runtime']['expected']['root_version'])
    root.gSystem=SimpleNamespace(Load=lambda name:0)
    root.TClass=SimpleNamespace(GetClass=lambda name:True)
    root.TFile=SimpleNamespace(Open=lambda name:File())
    root.RooLinkedList=LinkedList
    root.RooFit=SimpleNamespace(Constrain=lambda rows:('Constrain',[r.GetName() for r in rows]),GlobalObservables=lambda rows:('GlobalObservables',[r.GetName() for r in rows]))
    pm=types.ModuleType('HiggsAnalysis.CombinedLimit.PhysicsModel')
    pm.PhysicsModel=type('PhysicsModel',(),{'__module__':pm.__name__})
    pm.__file__=cfg['runtime']['artifacts'][1]['path']
    monkeypatch.setitem(sys.modules,'ROOT',root)
    monkeypatch.setitem(sys.modules,pm.__name__,pm)
    monkeypatch.setattr(n.platform,'machine',lambda:'x86_64')
    # Descriptive metadata is inert too: platform.platform() may launch uname -p.
    # Architecture admission and the unmocked-process refusal remain exercised below.
    monkeypatch.setattr(n.platform,'platform',lambda:'synthetic inert ROOT protocol platform')
    monkeypatch.delenv('CMSSW_VERSION',raising=False)
    commands=[]
    def invoke(command,directory,environment,log,deadline,**kwargs):
        commands.append(list(command))
        if '--help' in command:raw='synthetic help only\n'
        elif len(command)==1:raw=VERSION_LOG
        elif '-o' in command:
            Path(command[command.index('-o')+1]).write_bytes(b'Inert workspace blob; not ROOT or source model equivalence')
            raw='synthetic workspace builder\n'
        else:
            assert Path(command[1]).name=='ravel_native_probe.py'
            out=io.StringIO()
            try:
                with patch.object(sys,'argv',command[1:]),contextlib.redirect_stdout(out):
                    exec(compile(Path(command[1]).read_text(),command[1],'exec'),{'__file__':command[1]})
            finally:
                Path(log).write_text(out.getvalue())
            raw=out.getvalue()
        Path(log).write_text(raw)
        return raw
    monkeypatch.setattr(n,'_process',invoke)
    # Catch any accidental bypass of the inherited transport seam.
    monkeypatch.setattr(n.subprocess,'Popen',lambda *a,**kw:pytest.fail('unmocked process'))
    result=n.run({'input':str(cp)},tmp_path,tmp_path/'out')
    if failure!='success':
        assert result['status']=='failed' and not result['runtime_qualified_for_this_workspace']
        journal=c.read_journal(tmp_path/'out/native-work/ravel_derivative_points.jsonl')
        assert len(attempted)==2
        assert [e['status'] for e in journal[:5]]==['started','planned','running','returned','checked']
        assert journal[-2]['status']=='failed' and journal[-1]['status']=='reset'
        assert len([e for e in journal if e['status']=='returned'])==(1 if failure=='late_exception' else 2)
        assert any(p['path']=='native-work/ravel_derivative_points.jsonl' for p in result['retained_artifacts'])
        assert not (tmp_path/'out/native-derivative-estimates.json').exists()
        return
    assert result['status']=='passed' and result['fit'] is None
    assert result['commands']['fit'] is None and 'result_extraction' not in result['commands']
    assert options==[('Constrain',['theta']),('GlobalObservables',['nom'])]
    assert result['workspace_probe']['workspace']['channels']==['CR','SR']
    assert len(nll.calls)==result['inference']['native_nll_calls']
    assert not any('-M' in argv for argv in commands)
    assert not (tmp_path/'out/native-logs/native-fit.log').exists()
    assert json.loads((tmp_path/'out/native-derivative-estimates.json').read_text())==result['inference']['estimates']
    assert result['workspace_probe']['derivatives']['final_state']==c.capture(w,mc)
    assert result['inference']['estimates']['levels'][0]['hessian']==[[10.,7.],[7.,22.]]


def test_new_generated_paths_are_reserved_only_for_the_opt_in_branch(tmp_path):
    cp,cfg,*_=fixture(tmp_path)
    asset=tmp_path/'unused.py';asset.write_text('# supplied source, not imported\n')
    cfg['model']['files'].append({'path':str(asset),'sha256':hashlib.sha256(asset.read_bytes()).hexdigest(),'staged_path':'ravel_derivative_kernel.py'})
    cp.write_text(json.dumps(cfg))
    assert asset in n.inputs({'input':str(cp)},tmp_path)
    cfg['schema_version']=3;cfg['fit'].update(method='MultiDimFit',points=None,fixed_witness_points=[])
    cfg['derivatives']={'anchor':{},'axes':[{'name':'r','step':.25}],'max_points':32}
    cp.write_text(json.dumps(cfg))
    with pytest.raises(ValueError,match='conflicting staged'):n.inputs({'input':str(cp)},tmp_path)


def test_unreviewed_root_global_default_refuses_in_public_inputs_before_any_worker(tmp_path):
    cp,cfg,_=config(tmp_path);cfg['runtime']['expected']['root_version']='6.28/00';cp.write_text(json.dumps(cfg))
    with pytest.raises(ValueError,match='source-qualified exact ROOT'):n.inputs({'input':str(cp)},tmp_path)
