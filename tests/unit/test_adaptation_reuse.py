"""Portable executable reuse operations; not unknown-model/physics efficacy."""
from copy import deepcopy
import hashlib,importlib.util,json
from pathlib import Path
import sys
import pytest
MODULE=Path(__file__).resolve().parents[2]/'src/ravel/workflow/adaptation_reuse.py'
spec=importlib.util.spec_from_file_location('ravel.workflow.adaptation_reuse',MODULE)
a=importlib.util.module_from_spec(spec);sys.modules[spec.name]=a;spec.loader.exec_module(a)


def write(path,value):
    path.write_text(json.dumps(value,sort_keys=True,indent=2)+'\n')
    return {'path':path.name,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'size':path.stat().st_size}


def setup(tmp_path):
    program='def ADAPTATION(rows):\n    totals = {}\n    for group, weight in rows:\n        totals[group] = totals.get(group, 0) + weight\n    return sum(value * value for value in totals.values())\n'
    source=tmp_path/'group_program.py';source.write_text(program)
    observation=write(tmp_path/'measurement.json',{'declared_program_output':10,'limitations':'Explicit programming fixture, not native observation.'})
    grouped={'id':'group_cross_terms','summary':'Preserve signed same-group cross terms before quadratic accumulation.',
        'domain':'weighted program','scope':'Supplied programming rows; no native detector or interval calibration.',
        'facets':{'group_unit':'original group','weight_kind':'signed','output':'quadratic'},
        'source':{'path':source.name,'sha256':hashlib.sha256(source.read_bytes()).hexdigest()},
        'fragment':{'first_line':1,'last_line':len(program.splitlines()),'text':program},
        'parameters':[{'id':'function','token':'ADAPTATION','kind':'identifier','expected_occurrences':1}],
        'observations':[{'id':'prior_case','status':'reported_success','scope':'One supplied program test; truth not authenticated here.','artifact':observation}],
        'reopen_when':['New group identities, effective weights, input parser or native runtime require fresh qualification.']}
    wrong=deepcopy(grouped);wrong.update(id='fill_squares',summary='Independent per-fill squares without group cross terms.')
    wrong['facets']['group_unit']='individual fill';wrong['observations'][0]['status']='reported_failure'
    catalog=write(tmp_path/'catalog.json',{'schema_version':1,'entries':[wrong,grouped]})
    request={'schema_version':1,'catalog':catalog,'task':{'id':'new_group_task',
        'question':'Reuse signed same-group quadratic accumulation for a new program input.',
        'domain':'weighted program','scope':'New author-known programming cases, no statistical independence claim.',
        'facets':{'group_unit':'original group','weight_kind':'signed','output':'quadratic','runtime':'new stdlib'},
        'source_obligations':[{'id':'all_groups','description':'Keep every original group, signed/zero weight and the full requested result.'}]},
        'top_k':2,'max_context_bytes':16384}
    return request,grouped


def rewrite_catalog(tmp_path,request,change):
    catalog=json.loads((tmp_path/'catalog.json').read_text());change(catalog)
    request['catalog']=write(tmp_path/'catalog.json',catalog)


def test_relevant_executable_adaptation_ranks_first_and_scope_differences_remain(tmp_path):
    request,_=setup(tmp_path);record=a.retrieve(request,base_dir=tmp_path)
    first=record['selected'][0]
    assert first['id']=='group_cross_terms'
    assert first['scope_differences']==[{'facet':'runtime','origin':None,'target':'new stdlib'}]
    assert first['reported_observations'][0]['status']=='reported_success'
    assert first['source_obligations']==request['task']['source_obligations']
    assert first['fresh_execution_and_full_scope_review_required'] is True
    assert record['semantic_equivalence_proved'] is record['supplied_report_truth_verified'] is False


def test_failed_or_untested_observations_remain_eligible_not_blacklisted(tmp_path):
    request,_=setup(tmp_path)
    rewrite_catalog(tmp_path,request,lambda c:c['entries'][1]['observations'][0].update(status='untested'))
    record=a.retrieve(request,base_dir=tmp_path)
    assert [r['id'] for r in record['selected']]==['group_cross_terms','fill_squares']
    assert record['selected'][0]['reported_observations'][0]['status']=='untested'
    assert record['selected'][1]['reported_observations'][0]['status']=='reported_failure'


def test_instantiation_emits_executable_new_proposal_with_preserved_obligations(tmp_path):
    request,_=setup(tmp_path);record=a.retrieve(request,base_dir=tmp_path)
    proposed=a.prepare(record,'group_cross_terms',{'function':'new_accumulator'},base_dir=tmp_path)
    namespace={};exec(compile(proposed['controlled_source'],'fresh-program','exec'),namespace)
    # Genuine execution of the prepared source on new signed/zero/repeated groups.
    rows=[('a',1),('a',2),('b',-1),('z',0),('b',2)]
    assert namespace['new_accumulator'](rows)==10
    assert sum(weight*weight for _,weight in rows)==10  # Numerical coincidence is not a distinguishing witness.
    changed=[('a',2),('a',3),('b',-2),('z',0)]
    assert namespace['new_accumulator'](changed)==29
    assert sum(weight*weight for _,weight in changed)==17
    assert proposed['source_obligations']==request['task']['source_obligations']
    assert 'new_accumulator' in proposed['literal_source_diff']
    assert proposed['old_votes_carried']==[] and proposed['execution_authorized'] is False
    assert proposed['scientific_acceptance'] is False


@pytest.mark.parametrize('change',['source','observation'])
def test_changed_retained_code_or_observation_refuses_before_reuse(tmp_path,change):
    request,_=setup(tmp_path)
    path=tmp_path/('group_program.py' if change=='source' else 'measurement.json')
    path.write_text(path.read_text()+' ')
    with pytest.raises(ValueError):a.retrieve(request,base_dir=tmp_path)


@pytest.mark.parametrize('field',['text','first_line','last_line'])
def test_source_span_cannot_retarget_or_truncate_literal_adaptation(tmp_path,field):
    request,_=setup(tmp_path)
    def mutate(c):c['entries'][1]['fragment'][field]='return 0\n' if field=='text' else 2 if field=='first_line' else 4
    rewrite_catalog(tmp_path,request,mutate)
    with pytest.raises(ValueError):a.retrieve(request,base_dir=tmp_path)


def test_rank_ties_are_catalog_order_independent(tmp_path):
    request,_=setup(tmp_path)
    def mutate(c):c['entries'][0]=deepcopy(c['entries'][1]);c['entries'][0]['id']='alternate'
    rewrite_catalog(tmp_path,request,mutate)
    first=a.retrieve(request,base_dir=tmp_path)
    rewrite_catalog(tmp_path,request,lambda c:c['entries'].reverse())
    second=a.retrieve(request,base_dir=tmp_path)
    assert [r['id'] for r in first['selected']]==[r['id'] for r in second['selected']]


def test_small_source_budget_keeps_complete_omission_census(tmp_path):
    request,_=setup(tmp_path);request['max_context_bytes']=256
    record=a.retrieve(request,base_dir=tmp_path)
    assert record['selected']==[]
    assert {r['id'] for r in record['omitted']}=={'group_cross_terms','fill_squares'}
    assert all(r['reason']=='context_byte_bound' for r in record['omitted'])
    assert record['new_task_obligations']==request['task']['source_obligations']


@pytest.mark.parametrize('bindings',[{}, {'function':'bad;execute()'}, {'function':True}, {'function':'ok','extra':1}])
def test_only_complete_typed_source_parameters_are_instantiated(tmp_path,bindings):
    request,_=setup(tmp_path);record=a.retrieve(request,base_dir=tmp_path)
    with pytest.raises(ValueError):a.prepare(record,'group_cross_terms',bindings,base_dir=tmp_path)


def test_rehashed_retrieval_cannot_change_source_scope_or_carry_old_acceptance(tmp_path):
    request,_=setup(tmp_path);record=a.retrieve(request,base_dir=tmp_path)
    record['selected'][0]['scientific_acceptance']=True
    with pytest.raises(ValueError):a.prepare(record,'group_cross_terms',{'function':'new'},base_dir=tmp_path)


def test_complete_normal_input_inventory_contains_catalog_source_and_observation(tmp_path):
    request,_=setup(tmp_path);pins=a.input_pins(request,base_dir=tmp_path)
    assert {Path(pin['path']).name for pin in pins}=={'catalog.json','group_program.py','measurement.json'}
    assert len(pins)==3


def test_one_pass_substitution_does_not_recursively_replace_new_source_identifiers(tmp_path):
    request,_=setup(tmp_path)
    program='def ALPHA():\n    return BETA\n';(tmp_path/'group_program.py').write_text(program)
    def mutate(c):
        for row in c['entries']:
            row['source']['sha256']=hashlib.sha256(program.encode()).hexdigest()
            row['fragment']={'first_line':1,'last_line':2,'text':program}
            row['parameters']=[{'id':'name','token':'ALPHA','kind':'identifier','expected_occurrences':1},
                {'id':'value','token':'BETA','kind':'identifier','expected_occurrences':1}]
    rewrite_catalog(tmp_path,request,mutate)
    record=a.retrieve(request,base_dir=tmp_path)
    proposed=a.prepare(record,record['selected'][0]['id'],{'name':'BETA','value':'GAMMA'},base_dir=tmp_path)
    assert proposed['controlled_source']=='def BETA():\n    return GAMMA\n'
