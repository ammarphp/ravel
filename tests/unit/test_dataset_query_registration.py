"""The dataset-query operation is registered with the science dispatcher, its scope gate and the command line.

The operation's own code and its controls are in test_dataset_query_quantities.py."""
import json
from pathlib import Path

import pytest

from ravel.physics import dataset_query_quantities as adapter, dataset_query_quantities_core as c
from test_dataset_query_quantities import configuration


def test_existing_scope_gate_and_science_adapter_are_connected():
    from ravel.workflow import science
    assert science.MODES.count('dataset-query-quantities') == 1
    assert science.adapter({'mode':'dataset-query-quantities','task':{}}) is adapter
    assert science._new_capability({'mode':'dataset-query-quantities','task':{}})
    policy={'schema_version':2,'max_attempts':1,'review_policy':{'policy':{'max_redos':0,'claim_scopes':{c.SCOPE:{'actions':['delivery']}}}}}
    adapter.validate_scope(policy)
    policy['max_attempts']=2
    with pytest.raises(ValueError):adapter.validate_scope(policy)


def test_real_focused_registry_and_help_remain_well_formed(capsys):
    from ravel import cli
    assert cli.FOCUSED_COMMANDS['dataset-query-quantities'][0]=='physics.dataset_query_quantities'
    parsed=cli.parser().parse_args(['status','--rundir','synthetic'])
    assert parsed.command=='status'


def test_actual_ordinary_unapproved_plan_retains_scope_and_complete_intake(tmp_path):
    from ravel.workflow import science
    task,cfg,rows=configuration(tmp_path)
    actors={'proposer':'source-proposer-control','executor':'source-executor-control','physics_critic':'source-critic-control',
        'skeptical_verifier':'source-verifier-control','physics_decider':'source-decider-control'}
    spec=adapter.specification(task,source='Explicit synthetic ordinary metadata control, no native process',
        assumptions=['Runtime, query and SF semantics are test premises, not physics qualification'],actors=actors,max_seconds=10)
    path=tmp_path/'spec.json';path.write_text(json.dumps(spec));rd=tmp_path/'ordinary-plan-control'
    planned=science.plan(rd,path)
    assert planned['schema_version']==2 and planned['max_attempts']==1
    assert Path(cfg['runtime']['python']['path']).as_posix() in planned['stage_binding']['inputs']
    assert not (rd/science.APPROVAL).exists() and not (rd/'execution_attempt.json').exists()
    assert science.packet(rd)['lifecycle_verdict']=='PENDING'
    assert (rd/'inputs/checkin1.json').is_file()
