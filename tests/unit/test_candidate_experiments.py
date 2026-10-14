"""Actual deterministic outcome controls for the private comparison proposal."""
from copy import deepcopy
import hashlib
import json
import pytest
from ravel.workflow import candidate_experiments as subject

def pin(path, root):
    raw = path.read_bytes()
    return {'path': str(path.relative_to(root)), 'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}

@pytest.fixture
def experiment(tmp_path):
    # Three declared algorithms actually evaluated on identical inputs. This is
    # a small algebraic capability test, not a frontier-physics efficacy result.
    candidates = [
        {'id':'seed', 'kind':'seed', 'parent':None, 'recipe_sha256':subject.digest('linear'),
         'components':['linear'], 'reason':'Seed linear approximation.'},
        {'id':'evolved', 'kind':'evolved', 'parent':'seed', 'recipe_sha256':subject.digest('quadratic'),
         'components':['linear','curvature'], 'reason':'Test the unvalidated curvature correction.'},
        {'id':'ablated', 'kind':'ablation', 'parent':'evolved', 'recipe_sha256':subject.digest('no-curvature'),
         'components':['linear'], 'reason':'Remove curvature to test component necessity.'},
    ]
    cases = [{'id':name, 'partition':partition, 'input_sha256':subject.digest(xs)}
             for name,partition,xs in [('dev','development',[0,1]), ('held','held_out',[2,3]),
                                       ('full','full_case',[-2,-1,0,1,2,3])]]
    samples = [[0,1],[2,3],[-2,-1,0,1,2,3]]
    trials = []
    for candidate in candidates:
        for case,xs in zip(cases,samples):
            actual = [x+x*x if candidate['id']=='evolved' else x for x in xs]
            truth = [x+x*x for x in xs]  # independent declared oracle
            score = sum((a-b)**2 for a,b in zip(actual,truth))
            rp = tmp_path/f"{candidate['id']}-{case['id']}-result.json"
            rp.write_text(json.dumps({'values':actual}))
            result = pin(rp,tmp_path)
            report = {'schema_version':1, 'candidate_id':candidate['id'], 'case_id':case['id'],
                      'input_sha256':case['input_sha256'], 'recipe_sha256':candidate['recipe_sha256'],
                      'result_sha256':result['sha256'], 'metric':'oracle squared residual',
                      'status':'passed', 'score':score, 'limitations':['Algebra control only.']}
            cp = tmp_path/f"{candidate['id']}-{case['id']}-check.json"
            cp.write_text(json.dumps(report))
            trials.append({'candidate_id':candidate['id'],'case_id':case['id'],
                           'result':result,'check':pin(cp,tmp_path)})
    plan = {'schema_version':1, 'scope':'Bounded seed/evolved/ablation algebra comparison',
            'metric':'oracle squared residual','direction':'minimize', 'candidates':candidates,
            'cases':cases,'trials':trials}
    return plan,tmp_path

def test_actual_paired_outcomes_and_component_ablation(experiment):
    plan,root = experiment
    result = subject.summarize(plan,base_dir=root)
    evolved,ablated = result['candidates'][1:]
    assert [r['score_delta_vs_parent'] for r in evolved['paired_comparisons']] == [-1,-97,-115]
    assert [r['score_delta_vs_parent'] for r in ablated['paired_comparisons']] == [1,97,115]
    assert all(r['favorable'] for r in evolved['paired_comparisons'])
    assert not any(r['favorable'] for r in ablated['paired_comparisons'])
    assert result['trial_count'] == 9
    assert all(r['next_action']=='request_full_case_review' for r in result['candidates'])
    assert result['execution_authorized'] is result['physics_validated'] is result['execution_identity_checked'] is False
    assert all(r['scientific_acceptance'] is False for r in result['candidates'])

def test_missing_outcome_stays_unknown_not_refutation(experiment):
    plan,root = experiment
    plan['trials'][4]['result'] = plan['trials'][4]['check'] = None
    result = subject.summarize(plan,base_dir=root)['candidates'][1]
    assert result['observations']['held']['status']=='not_observed'
    assert result['paired_comparisons'][1]['score_delta_vs_parent'] is None
    assert result['next_action']=='continue_declared_experiments'

def test_development_only_never_promotes_full_case(experiment):
    plan,root = experiment
    for row in plan['cases']: row['partition']='development'
    assert all(c['next_action']=='continue_declared_experiments'
               for c in subject.summarize(plan,base_dir=root)['candidates'])

def test_full_case_without_held_out_does_not_request_promotion(experiment):
    plan,root=experiment
    plan['cases'][1]['partition']='development'
    assert all(c['next_action']=='continue_declared_experiments'
               for c in subject.summarize(plan,base_dir=root)['candidates'])

def test_paired_difference_overflow_of_individually_finite_integers_refuses(experiment):
    plan,root=experiment
    for index,value in [(0,-10**308),(3,10**308)]:
        trial=plan['trials'][index]; path=root/trial['check']['path']
        report=json.loads(path.read_text()); report['score']=value
        path.write_text(json.dumps(report)); trial['check']=pin(path,root)
    with pytest.raises(ValueError,match='unrepresentable paired metric difference'):
        subject.summarize(plan,base_dir=root)

@pytest.mark.parametrize('mutation', ['drop','duplicate','foreign','cycle','missing_parent','not_ablation',
                                     'changed_input','changed_recipe','changed_metric','mixed_null'])
def test_identity_population_and_lineage_adversaries(experiment,mutation):
    plan,root = experiment
    if mutation=='drop': plan['trials'].pop()
    if mutation=='duplicate': plan['trials'][-1]=deepcopy(plan['trials'][0])
    if mutation=='foreign': plan['trials'][0]['candidate_id']='not_declared'
    if mutation=='cycle': plan['candidates'][1]['parent']='ablated'
    if mutation=='missing_parent': plan['candidates'][1]['parent']='not_declared'
    if mutation=='not_ablation': plan['candidates'][2]['components']=['linear','curvature']
    if mutation=='changed_input': plan['cases'][0]['input_sha256']='a'*64
    if mutation=='changed_recipe': plan['candidates'][0]['recipe_sha256']='a'*64
    if mutation=='changed_metric': plan['metric']='different numerical quantity'
    if mutation=='mixed_null': plan['trials'][0]['result']=None
    with pytest.raises(ValueError): subject.summarize(plan,base_dir=root)

@pytest.mark.parametrize('kind', ['stale','symlink','traversal','empty','oversize'])
def test_artifact_refusals(experiment,kind,tmp_path):
    plan,root = experiment
    fact = plan['trials'][0]['result']; p = root/fact['path']
    if kind=='stale': p.write_text('{"values":[42]}')
    if kind=='symlink':
        target = root/'target.json'; target.write_bytes(p.read_bytes()); p.unlink(); p.symlink_to(target)
    if kind=='traversal': fact['path']='../outside.json'
    if kind=='empty': fact['size']=0
    if kind=='oversize': fact['size']=subject.MAX_BYTES+1
    with pytest.raises(ValueError): subject.summarize(plan,base_dir=root)

@pytest.mark.parametrize('field,value', [('score',True),('score',float('inf')),('score',None),('score',10**400),
                                      ('status','accepted'),('result_sha256','a'*64)])
def test_checker_cannot_claim_another_result_or_nonfinite_score(experiment,field,value):
    plan,root = experiment
    trial = plan['trials'][0]; cp=root/trial['check']['path']
    report=json.loads(cp.read_text()); report[field]=value; cp.write_text(json.dumps(report))
    trial['check']=pin(cp,root)
    with pytest.raises(ValueError): subject.summarize(plan,base_dir=root)

def test_failed_report_retained_and_cannot_make_paired_success(experiment):
    plan,root = experiment
    trial=plan['trials'][4]; cp=root/trial['check']['path']
    report=json.loads(cp.read_text()); report.update(status='failed',score=None)
    cp.write_text(json.dumps(report)); trial['check']=pin(cp,root)
    result=subject.summarize(plan,base_dir=root)['candidates'][1]
    assert result['observations']['held']['status']=='failed'
    assert result['paired_comparisons'][1]['favorable'] is None
    assert result['next_action']=='continue_declared_experiments'
