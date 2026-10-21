"""Fictional operator settings and immutable run authority controls."""
from copy import deepcopy
import json
from pathlib import Path

import pytest
from ravel.workflow import operating_mode as mode
from ravel.workflow.approval_authority import AGENT_MARKERS
from ravel.workflow.state_io import atomic_json
from ravel.workflow import rdj_custody

# The real protected-ledger reader, captured before any fixture fakes the transport.
PRODUCTION_OPERATOR_RECORDS = mode._operator_records


@pytest.fixture
def operator(tmp_path, monkeypatch):
    for name in (*AGENT_MARKERS, 'RAVEL_OPERATING_MODE', 'RAVEL_AUTONOMY_BOUNDS'):
        monkeypatch.delenv(name, raising=False)
    home = tmp_path / 'home'
    home.mkdir()
    monkeypatch.setattr(Path, 'home', lambda: home)
    project = tmp_path / 'project'
    project.mkdir()
    (project / '.ravel').mkdir()
    monkeypatch.chdir(project)
    # Fake only the privileged operator transport. Production has no issuer API.
    # Exact selection verification, hash-chain custody, mode and approval gates stay real.
    store = tmp_path / 'external-operator'
    def records(kind, target):
        return rdj_custody._read(store / kind / (mode._key(target) + '.jsonl'))
    def issue(kind, target, value):
        return rdj_custody._append(store / kind / (mode._key(target) + '.jsonl'),
            {'schema_version':1, 'kind':kind, 'target':str(Path(target).resolve()), 'value':value})
    records.issue = issue
    monkeypatch.setattr(mode, '_operator_records', records)
    return project


def issue_setting(selected, *, scope='project', project=None, bounds=None):
    value = {'mode':selected, 'source':'project' if scope=='project' else 'user_default',
             'bounds':deepcopy(mode.DEFAULT_BOUNDS if bounds is None else bounds)}
    mode._operator_records.issue('setting', mode.config_path(scope, project), value)


def set_operator_mode(selected, *, scope='project', project=None, bounds=None):
    issue_setting(selected, scope=scope, project=project, bounds=bounds)
    return mode.set_mode(selected, scope=scope, project=project, bounds=bounds)


def authorize_environment(project, selected='autonomous', bounds=None):
    mode._operator_records.issue('environment', mode.project_root(project),
        {'mode':selected, 'source':'operator_environment',
         'bounds':deepcopy(mode.DEFAULT_BOUNDS if bounds is None else bounds)})


def authorize_run(root, document, *, project=None):
    import hashlib
    root = Path(root).resolve()
    prompt, parent = mode._original(document, root)
    if parent is not None:
        return  # Children cannot request a new mode or budget.
    selected = mode.resolve(prompt=prompt, project=project or root)
    if selected['mode']=='autonomous':
        selected.pop('configured')
        mode._operator_records.issue('run', root, {'rundir':str(root),
            'prompt_sha256':hashlib.sha256(prompt.encode()).hexdigest(),
            **selected, 'budget_root':str(root)})


def initialize_trusted(root, document, **kwargs):
    authorize_run(root, document, project=kwargs.get('project'))
    return mode.initialize(root, document, **kwargs)


def test_safe_default_and_operator_receipts(operator):
    assert mode.resolve()['mode'] == 'physicist-in-the-loop'
    set_operator_mode('autonomous', scope='user')
    assert mode.resolve()['source'] == 'user_default'
    assert mode.resolve()['mode'] == 'autonomous'
    set_operator_mode('physicist-in-the-loop', project=operator)
    assert mode.resolve()['source'] == 'project'
    assert mode.resolve()['mode'] == 'physicist-in-the-loop'
    assert mode.resolve(prompt='Please operate autonomously.')['source'] == 'explicit_request'
    assert mode.resolve(prompt='Please operate autonomously.')['mode'] == 'autonomous'


def test_environment_and_request_precedence(operator, monkeypatch):
    set_operator_mode('physicist-in-the-loop')
    authorize_environment(operator)
    monkeypatch.setenv('RAVEL_OPERATING_MODE', 'autonomous')
    assert mode.resolve()['source'] == 'operator_environment'
    assert mode.resolve(prompt='Do not run autonomously.')['mode'] == 'physicist-in-the-loop'
    assert mode.resolve(prompt='If ready, run autonomously.')['mode'] == 'physicist-in-the-loop'
    monkeypatch.setenv('RAVEL_OPERATING_MODE', 'typo')
    with pytest.raises(ValueError, match='RAVEL_OPERATING_MODE'):
        mode.resolve()


@pytest.mark.parametrize('prompt', [
    'Please use physicist-in-the-loop mode.',
    'Use physicist-in-the-loop mode for this task.',
    'Please ask for my approval before every check-in.',
    'Ask me for permission before proceeding.',
    'Wait for my confirmation before continuing.',
])
def test_human_steering_never_inherits_an_autonomous_default(operator, prompt):
    set_operator_mode('autonomous')
    selected = mode.resolve(prompt=prompt)
    assert selected['mode'] == 'physicist-in-the-loop'
    assert selected['source'] == 'explicit_request'
    assert mode.resolve(prompt='Run autonomously. ' + prompt)['mode'] == 'physicist-in-the-loop'


@pytest.mark.parametrize('marker', AGENT_MARKERS)
def test_agent_cannot_change_mode(operator, monkeypatch, marker):
    monkeypatch.setenv(marker, 'agent')
    with pytest.raises(ValueError, match='operator'):
        set_operator_mode('autonomous')
    assert not mode.config_path('project').exists()


def test_handwritten_configuration_is_not_operator_authority(operator):
    atomic_json(mode.config_path('project'), {'mode': 'autonomous'})
    with pytest.raises(ValueError, match='operator change receipt'):
        mode.resolve()


def test_frozen_mode_ignores_later_defaults_and_environment(operator, monkeypatch):
    set_operator_mode('autonomous')
    root = operator / 'runs' / 'fictional'
    document = {'prompt': 'Inspect the fictional polynomial.'}
    first = initialize_trusted(root, document)
    set_operator_mode('physicist-in-the-loop')
    monkeypatch.setenv('RAVEL_OPERATING_MODE', 'physicist-in-the-loop')
    assert mode.initialize(root, document) == first
    assert mode.frozen(root)['mode'] == 'autonomous'
    with pytest.raises(ValueError, match='different original request'):
        mode.frozen(root, document={'prompt': 'Different request'})


@pytest.mark.parametrize('mutation', ['delete', 'edit', 'copy'])
def test_run_mode_mutations_refuse(operator, mutation):
    root = operator / 'run'
    initialize_trusted(root, {'prompt': 'Fictional task'})
    path = root / mode.RUN_RECORD
    if mutation == 'delete':
        path.unlink()
    elif mutation == 'edit':
        value = json.loads(path.read_text()); value['mode'] = 'autonomous'; atomic_json(path, value)
    else:
        other = operator / 'other'
        atomic_json(other / mode.RUN_RECORD, json.loads(path.read_text()))
        root = other
    with pytest.raises(ValueError):
        mode.frozen(root)


@pytest.mark.parametrize('existing', ['run_state.json','execution_state.json'])
def test_existing_run_cannot_select_new_mode(operator, existing):
    root = operator / 'old'; root.mkdir()
    atomic_json(root / existing, {})
    with pytest.raises(ValueError, match='existing run'):
        initialize_trusted(root, {'prompt': 'Task'})


@pytest.mark.parametrize('field,value', [('max_redos', True), ('max_seconds', -1),
                                      ('compute_plans', ['invented']), ('max_events', float('inf'))])
def test_invalid_bounds_refused(operator, field, value):
    bounds = deepcopy(mode.DEFAULT_BOUNDS); bounds[field] = value
    with pytest.raises(ValueError):
        set_operator_mode('autonomous', bounds=bounds)


def test_cli_surface(operator, capsys):
    issue_setting('autonomous')
    assert mode.main(['set', 'autonomous', '--scope', 'project']) == 0
    assert mode.main(['show']) == 0
    assert 'autonomous' in capsys.readouterr().out


def test_children_inherit_frozen_source_and_share_budget(operator, monkeypatch):
    import hashlib
    bounds=deepcopy(mode.DEFAULT_BOUNDS);bounds['max_seconds']=12
    set_operator_mode('autonomous', bounds=bounds)
    parent=operator/'parent'
    document={'prompt':'Inspect the fictional polynomial.'}
    atomic_json(parent/'inputs/task_contract.json',document)
    initialize_trusted(parent,document)
    path=parent/'inputs/task_contract.json'
    pin={'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'size':path.stat().st_size}
    child_document={'goal_binding':{'contract':pin,'assignment_id':'N1'}}
    set_operator_mode('physicist-in-the-loop')
    child=parent/'child'
    atomic_json(child/'inputs/task_contract.json',child_document)
    value=initialize_trusted(child,child_document)
    assert value['mode']=='autonomous' and value['source']=='project'
    assert value['budget_root']==str(parent)
    with mode.launch_reservation(parent,['inert'],{'stage':'science','max_seconds':8,'events':0}):
        pass
    with pytest.raises(ValueError,match='aggregate'):
        with mode.launch_reservation(child,['inert'],{'stage':'science','max_seconds':8,'events':0}):
            pass
    assert mode.frozen(child,document=child_document)==value


@pytest.mark.parametrize('context', [
    {'stage':'unlisted','max_seconds':1,'events':0},
    {'stage':'science','max_seconds':None,'events':0},
    {'stage':'science','max_seconds':float('nan'),'events':0},
    {'stage':'science','max_seconds':1,'events':True},
    {'stage':'science','max_seconds':1,'events':100001},
])
def test_launch_scope_and_resource_refusals(operator, context):
    set_operator_mode('autonomous')
    root=operator/'run';initialize_trusted(root,{'prompt':'Task'})
    with pytest.raises(ValueError):
        with mode.launch_reservation(root,['inert'],context):
            pytest.fail('invalid launch was admitted')


def test_deleted_launch_journal_cannot_reset_budget(operator):
    set_operator_mode('autonomous')
    root=operator/'run';initialize_trusted(root,{'prompt':'Task'})
    context={'stage':'science','max_seconds':1,'events':0}
    with pytest.raises(RuntimeError):
        with mode.launch_reservation(root,['inert'],context):
            raise RuntimeError('inert process failed to start')
    with pytest.raises(ValueError,match='redo ceiling'):
        with mode.launch_reservation(root,['inert'],context):
            pass


def test_retained_source_selection_does_not_depend_on_live_science_plan(operator):
    from ravel.workflow import scientific_autonomy as autonomy, science, task_completion
    import hashlib
    root=operator/'archived';root.mkdir()
    text='Please operate autonomously.'
    document={'prompt':text,'task_mode':'research','task_requirements':task_completion.initial_requirements(text)}
    user=root/'message.txt';user.write_text(text)
    declared=autonomy.prepare_declaration(document,root/'delegation.json',
        user_text={'path':str(user),'sha256':hashlib.sha256(user.read_bytes()).hexdigest()},
        quote=text, origin='initial_prompt', delegate_actor='fixture', actions=['approve_plan'],
        bounds={'compute_plans':['none'],'allowed_changed_paths':[],'allowed_stages':[],'max_redos':0},
        task_class='research_analysis', base_dir=root)
    sources={str(root/science.SPEC):json.dumps(declared['document']).encode(),
             str(root/'delegation.json'):(root/'delegation.json').read_bytes(),str(user):user.read_bytes()}
    assert not (root/science.PLAN).exists()
    result=mode.receipt(root,sources=sources)
    assert result['mode']=='autonomous' and result['source']=='explicit_request'


def test_public_cli_uses_operator_receipts(operator,capsys):
    from ravel import cli
    assert cli.main(['mode','set','autonomous'])==1
    issue_setting('autonomous')
    assert cli.main(['mode','set','autonomous'])==0
    assert cli.main(['mode','show'])==0
    assert 'autonomous' in capsys.readouterr().out
