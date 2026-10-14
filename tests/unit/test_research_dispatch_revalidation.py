"""Last-boundary source guards. All dispatches are sentinels, no jobs."""
from method_decision_fixture import admit_method
from copy import deepcopy
from pathlib import Path
import pytest
from ravel.workflow import research_cycle as cycle, science
from test_research_cycle import contract,experiment,propose,hypotheses,write,phase_request,run_one
from test_research_failure_cycle import connect,existing_failure


def prepared(base):
    root=base/'cycle';cycle.create(root,contract(base),base_dir=base, evaluation_harness=True);propose(base,root)
    connect(base,root)
    e=experiment(base,'paired',grouped=True,parent='failed-parent')
    cycle.design(root,e);rd=base/'paired-run';cycle.prepare_experiment(root,'paired',rd); admit_method(rd)
    science.approve(rd,'Own source guard control, no job authority.',scripted=True)
    return root,rd


def forbid(monkeypatch):
    calls=[]
    monkeypatch.setattr(science,'run',lambda *a,**k:calls.append((a,k)) or 0)
    return calls


def test_report_drift_after_plan_never_dispatches(tmp_path,monkeypatch):
    root,_=prepared(tmp_path);calls=forbid(monkeypatch)
    (tmp_path/'critic-source-report.json').write_text('{"changed":true}\n')
    with pytest.raises(ValueError):cycle.run_experiment(root,'paired')
    assert calls==[]


def test_reopened_failed_ancestor_after_plan_never_dispatches(tmp_path,monkeypatch):
    root,_=prepared(tmp_path);calls=forbid(monkeypatch)
    cycle.revise_premise(root,'pairing','New explicitly changed scientific source premise.',basis=[],reason='Source guard intervention')
    with pytest.raises(ValueError):cycle.run_experiment(root,'paired')
    assert calls==[]


def test_prediction_premise_after_plan_is_current_even_when_design_has_none(tmp_path,monkeypatch):
    root=tmp_path/'cycle';c=contract(tmp_path);c['premises'].append({'id':'rival-basis','statement':'Own declared rival premise','basis':[]})
    cycle.create(root,c,base_dir=tmp_path, evaluation_harness=True);rows=hypotheses()
    rows[0]['premise_ids']=['rival-basis']
    cycle.propose(root,rows,origin={'kind':'supplied_source','pin':write(tmp_path/'rivals.json',rows),'description':'Own control rival source'})
    connect(tmp_path,root);e=experiment(tmp_path,'paired',grouped=True,parent='failed-parent',premise_ids=[])
    cycle.design(root,e);rd=tmp_path/'paired-run';cycle.prepare_experiment(root,'paired',rd); admit_method(rd)
    science.approve(rd,'Own control, never a native/model job',scripted=True)
    calls=forbid(monkeypatch)
    cycle.revise_premise(root,'rival-basis','Changed rival basis only.',basis=[],reason='Own source control')
    with pytest.raises(ValueError):cycle.run_experiment(root,'paired')
    assert calls==[]


def test_current_complete_parent_reaches_single_ordinary_dispatch(tmp_path,monkeypatch):
    root,_=prepared(tmp_path);calls=forbid(monkeypatch)
    assert cycle.run_experiment(root,'paired')==0 and len(calls)==1


def test_original_declared_resource_wall_cannot_be_reset_to_zero(tmp_path):
    root=tmp_path/'cycle';cycle.create(root,contract(tmp_path),base_dir=tmp_path, evaluation_harness=True);propose(tmp_path,root)
    _,document,_=existing_failure(tmp_path)
    with pytest.raises(ValueError,match='original declared wall'):
        cycle.import_failed_stage(root,'retained',document,premise_ids=[],predictions={'grouped':None},historical_cost={'calls':0,'output_tokens':0,'wall_seconds':0,'native_attempts':1})
    assert cycle._load(root)[1]['resource_ledger']==[]


def test_unavailable_old_resource_bound_refuses_instead_of_zero_default(tmp_path,monkeypatch):
    root=tmp_path/'cycle';cycle.create(root,contract(tmp_path),base_dir=tmp_path, evaluation_harness=True);propose(tmp_path,root)
    _,document,_=existing_failure(tmp_path,with_resource=False)
    monkeypatch.setattr(science,'SPEC','inputs/nonexistent-original-spec.json')
    with pytest.raises(ValueError,match='wall unavailable'):
        cycle.import_failed_stage(root,'retained',document,premise_ids=[],predictions={'grouped':None},historical_cost={'calls':0,'output_tokens':0,'wall_seconds':30,'native_attempts':1})


def test_added_preconstruction_phase_after_plan_blocks_dispatch(tmp_path,monkeypatch):
    root=tmp_path/'cycle';cycle.create(root,contract(tmp_path),base_dir=tmp_path, evaluation_harness=True);propose(tmp_path,root)
    cycle.design(root,experiment(tmp_path,'paired',grouped=True));rd=tmp_path/'planned-run';cycle.prepare_experiment(root,'paired',rd); admit_method(rd)
    science.approve(rd,'Own sentinel engineering control',scripted=True)
    cycle.design(root,experiment(tmp_path,'lifecycle-check',grouped=False))
    request=phase_request(root)
    cycle.configure_phases(root,write(tmp_path/'phase.json',request),check_contracts={'lifecycle':{'experiment_id':'lifecycle-check','required_check_ids':['integrity','math'],'purpose':'adapter_lifecycle'}},preconstruction_checks={'paired':['lifecycle'],'lifecycle-check':[]})
    calls=forbid(monkeypatch)
    with pytest.raises(ValueError):cycle.run_experiment(root,'paired')
    assert calls==[]


def test_missing_observable_never_becomes_a_declared_json_null_outcome(tmp_path):
    root=tmp_path/'cycle';cycle.create(root,contract(tmp_path),base_dir=tmp_path, evaluation_harness=True);propose(tmp_path,root)
    e=experiment(tmp_path,'paired',grouped=True)
    e['observable']={'pointer':'/absent-measurement','outcomes':{'null-outcome':None,'number':1.0}}
    e['predictions']={'independent':'null-outcome','grouped':'number','unknown':None}
    run_one(tmp_path,root,e)
    observation=cycle._load(root)[1]['experiments'][0]['observation']
    assert observation['measurement_present'] is False and observation['outcome'] is None
    assert set(observation['prediction_comparison'].values())=={'unknown'}
    assert observation['result_category']=='unresolved_measurement'
