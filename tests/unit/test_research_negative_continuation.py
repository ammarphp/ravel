"""Source-only negative continuation; synthetic receipts, no worker launches."""
from copy import deepcopy
import pytest
from ravel.workflow import research_cycle as cycle,science
from test_research_cycle import contract,experiment,propose,hypotheses,write
from test_research_failure_cycle import existing_failure


def observed_failure(base,monkeypatch):
 root=base/'cycle';cycle.create(root,contract(base),base_dir=base, evaluation_harness=True);propose(base,root)
 rd,pin,feedback=existing_failure(base)
 document=cycle._read(pin,base)
 cycle.design(root,experiment(base,'paired',grouped=True))
 _,state=cycle._load(root);e=state['experiments'][0]
 e.update(rundir=str(rd),plan=write(base/'synthetic-ordinary-plan.json',{'source_fixture':True}),
  observation={'receipt':cycle._pin(document['record']['path']),'attempt_id':document['attempt_id'],
   'execution_status':'failed','result':None,'measured':None,'outcome':None,
   'prediction_comparison':{h:'unknown' for h in e['predictions']},
   'result_category':'execution_or_adapter_failure_unresolved','scientific_acceptance':False})
 cycle._charge(state,'experiment:paired',e['cost'],e['study'])
 cycle._commit(root,state,'synthetic_observed_failure_fixture')
 monkeypatch.setattr(science,'verify_plan',lambda *a,**k:{'explicit_test_only_plan':True})
 return root,pin,feedback


def test_attach_retains_original_failed_observation_without_second_debit(tmp_path,monkeypatch):
 root,pin,_=observed_failure(tmp_path,monkeypatch);_,before=cycle._load(root)
 after=cycle.attach_failed_stage(root,'paired',pin)
 e=after['experiments'][0]
 assert e['kind']=='attached_failed_stage' and e['failure_origin']=='this_cycle_observed_ordinary_attempt'
 assert e['original_ordinary_observation']==before['experiments'][0]['observation']
 assert after['resource_ledger']==before['resource_ledger'] and len(after['resource_ledger'])==1
 assert e['observation']['result_category']=='scientific_unresolved' and e['adjudication'] is None
 assert set(e['observation']['prediction_comparison'].values())=={'unknown'}


def test_attached_failure_consumes_actual_attributed_critique_and_whole_successor(tmp_path,monkeypatch):
 root,pin,feedback=observed_failure(tmp_path,monkeypatch)
 cycle.attach_failed_stage(root,'paired',pin)
 cycle.diagnostic_feedback(root,'paired',feedback,allow_control=True)
 proposal=cycle.feedback_packet(root,'paired');value=cycle._read(proposal,tmp_path)
 assert value['failed_parent_acceptance_remains_false']
 assert value['diagnostic_feedback']['sha256']==feedback['sha256']
 cycle.design(root,experiment(tmp_path,'revised',grouped=True,parent='paired'))
 assert cycle.select(root)['selected']=='revised'
 assert cycle.status(root)['connected_task_complete'] is False


def test_another_attempt_cannot_be_transplanted_to_existing_observation(tmp_path,monkeypatch):
 root,_,_=observed_failure(tmp_path,monkeypatch)
 other=tmp_path/'other';other.mkdir();_,pin,_=existing_failure(other)
 with pytest.raises(ValueError):
  cycle.attach_failed_stage(root,'paired',pin)
 assert cycle._load(root)[1]['experiments'][0].get('kind') is None


def test_same_failure_attachment_is_one_time_and_never_a_retry(tmp_path,monkeypatch):
 root,pin,_=observed_failure(tmp_path,monkeypatch);cycle.attach_failed_stage(root,'paired',pin)
 with pytest.raises(ValueError):cycle.attach_failed_stage(root,'paired',pin)
 for method in (cycle.run_experiment,cycle.observe,cycle.adjudicate):
  with pytest.raises(ValueError):method(root,'paired')
 with pytest.raises(ValueError):cycle.prepare_experiment(root,'paired',tmp_path/'retry')


def test_attachment_requires_existing_exact_reservation(tmp_path,monkeypatch):
 root,pin,_=observed_failure(tmp_path,monkeypatch);_,state=cycle._load(root)
 state['resource_ledger']=[];cycle._commit(root,state,'own_adverse_missing_reservation')
 with pytest.raises(ValueError,match='existing ordinary operation reservation'):
  cycle.attach_failed_stage(root,'paired',pin)


def test_successful_measurement_cannot_be_reclassified_as_failed_diagnosis(tmp_path,monkeypatch):
 root,pin,_=observed_failure(tmp_path,monkeypatch);_,state=cycle._load(root)
 state['experiments'][0]['observation']['execution_status']='succeeded'
 cycle._commit(root,state,'own_adverse_success_label')
 with pytest.raises(ValueError,match='ordinary failure'):
  cycle.attach_failed_stage(root,'paired',pin)


def test_attached_report_drift_does_not_supply_new_successor_authority(tmp_path,monkeypatch):
 root,pin,feedback=observed_failure(tmp_path,monkeypatch)
 cycle.attach_failed_stage(root,'paired',pin);cycle.diagnostic_feedback(root,'paired',feedback,allow_control=True)
 (tmp_path/'critic-source-report.json').write_text('{"changed":true}\n')
 with pytest.raises(ValueError):cycle.feedback_packet(root,'paired')


def test_hypothesis_only_premise_change_has_visible_interpretation_scope(tmp_path,monkeypatch):
 root,pin,feedback=observed_failure(tmp_path,monkeypatch)
 cycle.attach_failed_stage(root,'paired',pin);cycle.diagnostic_feedback(root,'paired',feedback,allow_control=True)
 # This control changes the declared hypothesis-only premise binding, retaining
 # the independent measurement's own basis and historical comparison unchanged.
 _,state=cycle._load(root)
 row={'id':'interpretation','statement':'Own prospective interpretation basis','basis':[]}
 row=cycle._seal(row);state['premises'].append(row)
 state['hypotheses'][0]['premise_bindings']['interpretation']=row['sha256']
 cycle._commit(root,state,'own_hypothesis_only_fixture')
 old=deepcopy(cycle._load(root)[1]['experiments'][0]['observation'])
 cycle.revise_premise(root,'interpretation','Changed explanation basis.',basis=[],reason='Own source-only changed interpretation')
 value=cycle._read(cycle.feedback_packet(root,'paired'),tmp_path)
 view=value['current_applicability']
 assert view['measurement'] is True and view['prediction_interpretations']['independent'] is False
 assert value['observation']==old
 assert cycle.status(root)['experiments'][0]['prediction_interpretations_current']['independent'] is False
