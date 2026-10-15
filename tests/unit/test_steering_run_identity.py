"""The initialization command never gives a copied or renamed run fresh steering authority.

Each test builds a paused run, or a child bound to a vetoed parent, copies or renames the
directory, removes what a tidy-up would remove (the steering mirrors, and in the stricter cases
the steering text and the identity record), and then runs the command the dispatch refusal
names. The command must refuse and name the recorded location, the copy must stay refused, and
the pause or veto must still hold. At the original location the command stays idempotent.
"""
import json
import shutil

import pytest

from ravel.workflow import gate_wiring as gw, rdj_custody as custody
from test_steering_admission import (  # noqa: F401
    admitted_launch, machine_rules, quiet_stops, refused_launch)

INIT_COMMAND = 'ravel gate-wiring steer init --rundir <run>'


def prepared(tmp_path, name, contract):
    """A run directory prepared by hand: a task contract and nothing RAVEL wrote."""
    root = tmp_path / name
    (root / 'inputs').mkdir(parents=True)
    (root / 'inputs/task_contract.json').write_text(json.dumps(contract))
    return root


def command(*argv):
    return gw.main([str(value) for value in argv])


def init(root, capsys):
    """Run the initialization command; returns its exit status and what it printed to stderr."""
    capsys.readouterr()
    code = command('steer', 'init', '--rundir', root)
    return code, capsys.readouterr().err


def journal(root):
    return [row['record'] for row in custody.rows(root, 'steering')]


def strip(directory, removed):
    """Remove from a copied or renamed directory what ``removed`` names."""
    if 'mirrors' in removed:
        shutil.rmtree(directory / 'inputs/steering')
    if 'text' in removed and (directory / 'inputs/user-steering').exists():
        shutil.rmtree(directory / 'inputs/user-steering')
    if 'identity' in removed:
        (directory / custody.RUN_IDENTITY).unlink()


def refused_by_the_command(directory, recorded, capsys):
    """Dispatch names the initialization command; that command refuses and names the recorded location."""
    allowed, reason = gw.dispatch_permitted(directory, None)
    assert not allowed and 'custody is absent' in reason and INIT_COMMAND in reason
    identity = (directory / custody.RUN_IDENTITY).read_text() if (directory / custody.RUN_IDENTITY).exists() else None
    code, err = init(directory, capsys)
    assert code == 2 and 'Traceback' not in err
    assert str(recorded) in err and 'renamed or copied run' in err and 'Nothing was initialized' in err
    assert f'return the directory to {recorded}' in err
    # Nothing was written: no journal, no new identity, and the directory is still refused.
    assert journal(directory) == []
    now = (directory / custody.RUN_IDENTITY).read_text() if (directory / custody.RUN_IDENTITY).exists() else None
    assert now == identity
    assert not gw.dispatch_permitted(directory, None)[0]
    return err


@pytest.fixture
def paused(tmp_path, monkeypatch, machine_rules, capsys):
    quiet_stops(monkeypatch)
    root = prepared(tmp_path, 'study', {'request': 'a synthetic scalar study'})
    assert init(root, capsys)[0] == 0
    assert command('steer', 'pause', '--rundir', root, '--text', 'Pause the study.') == 0
    capsys.readouterr()
    assert gw.steering_state(root)['paused']
    return root


REMOVED = [('mirrors',), ('mirrors', 'text'), ('mirrors', 'identity'), ('mirrors', 'text', 'identity')]


@pytest.mark.parametrize('removed', REMOVED)
def test_copy_of_a_paused_run_is_refused_by_the_initialization_command(paused, tmp_path, monkeypatch, capsys, removed):
    copy = tmp_path / 'copy'
    shutil.copytree(paused, copy)
    strip(copy, removed)
    refused_by_the_command(copy, paused, capsys)
    refused_launch(copy, monkeypatch, None, 'custody is absent')
    # The original keeps its pause, and so does every later attempt on the copy.
    assert gw.steering_state(paused)['paused']
    refused_launch(paused, monkeypatch, None, 'paused')
    assert init(copy, capsys)[0] == 2 and journal(copy) == []


@pytest.mark.parametrize('removed', REMOVED)
def test_renamed_paused_run_is_refused_by_the_initialization_command(paused, tmp_path, monkeypatch, capsys, removed):
    before = journal(paused)
    moved = tmp_path / 'moved'
    paused.rename(moved)
    strip(moved, removed)
    refused_by_the_command(moved, paused, capsys)
    refused_launch(moved, monkeypatch, None, 'custody is absent')
    # The supported step: the directory returns to its recorded location, where the pause still holds.
    moved.rename(paused)
    assert journal(paused) == before
    assert gw.steering_state(paused)['paused']
    refused_launch(paused, monkeypatch, None, 'paused')


def test_initialization_at_the_original_location_is_idempotent_and_keeps_the_pause(paused, monkeypatch, capsys):
    before = journal(paused)
    identity = custody.run_identity(paused)
    for _ in range(2):
        assert init(paused, capsys)[0] == 0
    assert journal(paused) == before and custody.run_identity(paused) == identity
    assert gw.steering_state(paused)['paused']
    refused_launch(paused, monkeypatch, None, 'paused')
    # Mirrors removed in place change nothing either: custody decides.
    shutil.rmtree(paused / 'inputs/steering')
    assert init(paused, capsys)[0] == 0
    assert journal(paused) == before
    refused_launch(paused, monkeypatch, None, 'paused')


def test_run_steered_before_it_had_a_journal_record_keeps_its_pause_at_both_locations(tmp_path, monkeypatch,
                                                                                    machine_rules, capsys):
    """A run whose custody holds steering rows but no journal record (steered before its directory
    held run content) is initialized in place, and a copy of it is still refused."""
    quiet_stops(monkeypatch)
    root = tmp_path / 'earlier'
    gw.record_steering(root, 'Pause the study.', effect='pause')
    (root / 'inputs/task_contract.json').write_text(json.dumps({'request': 'an earlier study'}))
    assert 'journal_init' not in [record['event'] for record in journal(root)]
    before = journal(root)
    assert init(root, capsys)[0] == 0
    assert journal(root) == before and gw.steering_state(root)['paused']
    copy = tmp_path / 'earlier-copy'
    shutil.copytree(root, copy)
    strip(copy, ('mirrors', 'text'))
    code, err = init(copy, capsys)
    assert code == 2 and str(root) in err and 'the same task contract' in err
    assert journal(copy) == [] and not gw.dispatch_permitted(copy, None)[0]
    refused_launch(root, monkeypatch, None, 'paused')


# ---------------------------------------------------------------- a child bound to a vetoed parent

@pytest.fixture
def vetoed_child(tmp_path, monkeypatch, machine_rules, capsys):
    quiet_stops(monkeypatch)
    parent = prepared(tmp_path, 'parent', {'request': 'the parent study'})
    assert init(parent, capsys)[0] == 0
    child = prepared(tmp_path, 'experiment', {'request': 'one experiment of the parent study'})
    gw.bind_steering_child(parent, child, 'build')
    admitted_launch(child, monkeypatch, None)
    assert command('steer', 'veto', '--rundir', parent, '--text', 'Stop this branch.', '--affects', 'build') == 0
    capsys.readouterr()
    refused_launch(child, monkeypatch, None, 'parent steering: node or ancestor is vetoed')
    return parent, child


CHILD_REMOVED = [('mirrors',), ('mirrors', 'identity')]


@pytest.mark.parametrize('removed', CHILD_REMOVED)
def test_copy_of_a_child_bound_to_a_vetoed_parent_is_refused_by_the_initialization_command(
        vetoed_child, tmp_path, monkeypatch, capsys, removed):
    parent, child = vetoed_child
    copy = tmp_path / 'experiment-copy'
    shutil.copytree(child, copy)
    strip(copy, removed)
    err = refused_by_the_command(copy, child, capsys)
    if 'identity' in removed:
        # Recognized by its task contract, and the refusal says which study governs it.
        assert 'the same task contract' in err and f'bound to the study at {parent}' in err
    refused_launch(copy, monkeypatch, None, 'custody is absent')
    refused_launch(child, monkeypatch, None, 'parent steering: node or ancestor is vetoed')
    if 'identity' not in removed:
        # The parent does not bind a directory that carries the child's identity as a new child.
        with pytest.raises(custody.CustodyError, match='renamed or copied run'):
            gw.bind_steering_child(parent, copy, 'build')
        assert journal(copy) == []
    else:
        # Without the identity the parent can bind it again, and its veto then governs the copy too.
        gw.bind_steering_child(parent, copy, 'build')
        refused_launch(copy, monkeypatch, None, 'parent steering: node or ancestor is vetoed')


@pytest.mark.parametrize('removed', CHILD_REMOVED)
def test_renamed_child_bound_to_a_vetoed_parent_is_refused_by_the_initialization_command(
        vetoed_child, tmp_path, monkeypatch, capsys, removed):
    parent, child = vetoed_child
    before = journal(child)
    moved = tmp_path / 'experiment-moved'
    child.rename(moved)
    strip(moved, removed)
    refused_by_the_command(moved, child, capsys)
    refused_launch(moved, monkeypatch, None, 'custody is absent')
    moved.rename(child)
    assert journal(child) == before
    refused_launch(child, monkeypatch, None, 'parent steering: node or ancestor is vetoed')
    assert init(child, capsys)[0] == 0  # at its recorded location: idempotent, and the veto holds
    assert journal(child) == before
    refused_launch(child, monkeypatch, None, 'parent steering: node or ancestor is vetoed')


# ---------------------------------------------------------------- identity is bound where RAVEL creates a directory

def bound_here(root):
    """The identity record of a directory, its binding and its journal agree on this location."""
    identity = custody.run_identity(root)
    record = json.loads((root / custody.RUN_IDENTITY).read_text())
    assert record == {'schema_version': 1, 'kind': 'run-identity', 'run_id': identity, 'grants_authority': False}
    assert custody.location(identity) == str(root.resolve())
    bindings = [row['record'] for row in custody._read(custody._state() / custody.IDENTITIES)
                if row['record']['run_id'] == identity]
    assert bindings == [{'run_id': identity, 'path': str(root.resolve()), 'event': 'bind'}]
    initial = next(record for record in journal(root) if record['event'] == 'journal_init')
    assert initial['location']['run_id'] == identity and initial['location']['path'] == str(root.resolve())
    return identity


ROUTES = ['run', 'study', 'research', 'graph', 'scope']
# Routes whose directory holds a document that states the run (a task contract, a study plan, a graph specification).
STATED = ['run', 'study', 'graph']
PROMPT = 'Summarize the published limits on a synthetic scalar.'


@pytest.fixture
def create(tmp_path, monkeypatch, machine_rules):
    """Create a directory through one of the creation routes this test can drive without a toolchain."""
    monkeypatch.chdir(tmp_path)

    def make(route, name=None):
        root = tmp_path / (name or f'created-{route}')
        if route == 'run':
            from ravel import cli
            assert cli.main(['initiate', '--prompt', PROMPT, '--out', str(root)]) == 0
        elif route == 'study':
            from ravel.workflow import science
            from test_research_cycle import specification
            science.plan(root, specification(tmp_path, 'supplied-source-' + root.name, grouped=False)['path'])
        elif route == 'research':
            from ravel.workflow import research_cycle as cycle
            from test_research_cycle import contract
            cycle.create(root, contract(tmp_path), base_dir=tmp_path, evaluation_harness=True)
        elif route == 'graph':
            from ravel.workflow import agent_graph
            monkeypatch.setattr(agent_graph, 'validate', lambda spec: spec)
            monkeypatch.setattr(agent_graph, 'status', lambda root: {})
            agent_graph.create(root, {'graph_id': 'synthetic', 'nodes': [{'id': 'only', 'inputs': []}]})
        else:
            from ravel.workflow import graph_substrate as gs

            class Reached(Exception):
                pass

            def reached(*a):
                raise Reached()
            monkeypatch.setattr(gs, 'environment', lambda: None)
            monkeypatch.setattr(gs, '_context', reached)
            with pytest.raises(Reached):
                gs.run(root, 'synthetic-graph', {'node_id': 'only'})
        return root
    return make


@pytest.mark.parametrize('route', ROUTES)
def test_every_creation_route_binds_a_run_identity(create, route):
    first, second = create(route, 'first'), create(route, 'second')
    assert bound_here(first) != bound_here(second)
    assert gw.dispatch_permitted(first, None)[0] and gw.dispatch_permitted(second, None)[0]


def test_second_run_of_the_same_request_is_a_new_run(create):
    """Creation is not reconciled by the task contract: two runs of one request are two runs."""
    first, again = create('run', 'initiated'), create('run', 'initiated-again')
    assert (again / 'inputs/task_contract.json').read_bytes() == (first / 'inputs/task_contract.json').read_bytes()
    assert bound_here(again) != bound_here(first)
    assert gw.dispatch_permitted(again, None)[0] and gw.dispatch_permitted(first, None)[0]


@pytest.mark.parametrize('route, removed', [(route, ()) for route in ROUTES] + [(route, ('identity',)) for route in STATED])
@pytest.mark.parametrize('how', ['copy', 'rename'])
def test_copied_or_renamed_created_directory_is_refused_by_the_initialization_command(
        create, tmp_path, monkeypatch, capsys, route, how, removed):
    """Recognized by its identity record; a directory that states its run is recognized without it."""
    quiet_stops(monkeypatch)
    original = create(route)
    assert command('steer', 'pause', '--rundir', original, '--text', 'Pause the study.') == 0
    other = tmp_path / f'{route}-elsewhere'
    if how == 'copy':
        shutil.copytree(original, other, symlinks=True)
    else:
        original.rename(other)
    strip(other, ('mirrors', 'text') + removed)
    code, err = init(other, capsys)
    assert code == 2 and str(original) in err and 'renamed or copied run' in err, err
    assert journal(other) == [] and not gw.dispatch_permitted(other, None)[0]
    refused_launch(other, monkeypatch, None, 'custody is absent')
    if how == 'rename':
        other.rename(original)
    assert gw.steering_state(original)['paused']
    refused_launch(original, monkeypatch, None, 'paused')


# ---------------------------------------------------------------- what the command still admits, and what else it refuses

def test_prepared_directory_is_initialized_once_and_bound(tmp_path, monkeypatch, machine_rules, capsys):
    root = prepared(tmp_path, 'prepared', {'request': 'a directory prepared by hand'})
    assert not gw.dispatch_permitted(root, None)[0]
    assert init(root, capsys)[0] == 0
    identity = bound_here(root)
    assert init(root, capsys)[0] == 0 and bound_here(root) == identity
    assert [record['event'] for record in journal(root)] == ['journal_init']
    admitted_launch(root, monkeypatch, None)


def test_directory_with_the_task_contract_of_a_run_custody_knows_elsewhere_is_refused(tmp_path, machine_rules, capsys):
    """Without an identity the task contract is what a run is known by: the same contract at a
    second location is the same run, and a different contract is a different run."""
    first = prepared(tmp_path, 'first', {'request': 'one request'})
    assert init(first, capsys)[0] == 0
    same = prepared(tmp_path, 'same-contract', {'request': 'one request'})
    code, err = init(same, capsys)
    assert code == 2 and str(first) in err and 'the same task contract' in err
    assert journal(same) == [] and not (same / custody.RUN_IDENTITY).exists()
    different = prepared(tmp_path, 'different-contract', {'request': 'another request'})
    assert init(different, capsys)[0] == 0


def test_directory_holding_steering_text_recorded_elsewhere_is_refused(tmp_path, monkeypatch, machine_rules, capsys):
    quiet_stops(monkeypatch)
    root = tmp_path / 'bare'
    root.mkdir()
    assert init(root, capsys)[0] == 0
    assert command('steer', 'pause', '--rundir', root, '--text', 'Pause the study.') == 0
    copy = tmp_path / 'bare-copy'
    shutil.copytree(root, copy)
    strip(copy, ('mirrors', 'identity'))
    code, err = init(copy, capsys)
    assert code == 2 and str(root) in err and 'steering text' in err
    assert journal(copy) == []


def test_steering_text_recorded_at_this_location_does_not_refuse_its_initialization(tmp_path, machine_rules, capsys):
    """Text custody recorded here (a response, not a steering event) belongs to this location."""
    root = prepared(tmp_path, 'responded', {'request': 'a run with a recorded response'})
    custody.record_user_steering(root, 'A recorded response.')
    assert custody.rows(root, 'steering') == []
    assert init(root, capsys)[0] == 0


@pytest.mark.parametrize('record', ['{not json', '[]', '{"kind": "run-identity"}', '{"kind": "run-identity", "run_id": 7}',
                                    '{"kind": "other", "run_id": "abc"}'])
def test_unreadable_identity_record_refuses_initialization(tmp_path, machine_rules, capsys, record):
    root = prepared(tmp_path, 'damaged', {'request': 'a run with a damaged identity record'})
    (root / custody.RUN_IDENTITY).write_text(record)
    code, err = init(root, capsys)
    assert code == 2 and 'cannot be read' in err and 'Traceback' not in err
    assert journal(root) == []


def test_identity_custody_never_bound_refuses_initialization(tmp_path, machine_rules, capsys):
    root = prepared(tmp_path, 'from-elsewhere', {'request': 'a run from another machine'})
    (root / custody.RUN_IDENTITY).write_text(json.dumps({'schema_version': 1, 'kind': 'run-identity',
                                                         'run_id': 'f' * 32, 'grants_authority': False}))
    code, err = init(root, capsys)
    assert code == 2 and 'never bound' in err
    assert journal(root) == [] and custody.location('f' * 32) is None


def test_identity_binding_is_not_a_relocation_route(paused, tmp_path):
    """A run identified by its record is served only at its recorded location."""
    identity = custody.run_identity(paused)
    moved = tmp_path / 'moved'
    paused.rename(moved)
    with pytest.raises(ValueError, match='served only at its\\s+recorded location'):
        custody.relocate(moved, identity)
    with pytest.raises(custody.CustodyError, match='already bound'):
        custody.bind_run(moved, identity)
    assert custody.location(identity) == str(paused.resolve())


def test_unreadable_custody_of_another_run_refuses_initialization(tmp_path, machine_rules, capsys):
    """When custody elsewhere cannot be read, the command cannot establish that a directory is new."""
    first = prepared(tmp_path, 'first', {'request': 'one request'})
    assert init(first, capsys)[0] == 0
    ledger = custody.root(first) / 'steering.jsonl'
    ledger.write_text(ledger.read_text().replace('journal_init', 'journal_edit'))
    second = prepared(tmp_path, 'second', {'request': 'another request'})
    code, err = init(second, capsys)
    assert code == 2 and 'does not verify' in err and 'Traceback' not in err
    assert journal(second) == [] and not (second / custody.RUN_IDENTITY).exists()


def test_identity_record_removed_after_the_custody_store_was_lost_is_reconciled_by_documents(tmp_path, machine_rules, capsys):
    """Removing the identity record is no way around reconciliation: the documents still decide."""
    first = prepared(tmp_path, 'first', {'request': 'one request'})
    assert init(first, capsys)[0] == 0
    copy = tmp_path / 'copy'
    shutil.copytree(first, copy)
    (copy / custody.RUN_IDENTITY).write_text(json.dumps({'schema_version': 1, 'kind': 'run-identity',
                                                         'run_id': 'e' * 32, 'grants_authority': False}))
    assert init(copy, capsys)[0] == 2  # an identity custody never bound
    (copy / custody.RUN_IDENTITY).unlink()
    code, err = init(copy, capsys)
    assert code == 2 and str(first) in err and 'the same task contract' in err
    # A directory custody knows nothing about is admitted once its unknown identity record is removed.
    lost = prepared(tmp_path, 'lost-custody', {'request': 'a run whose custody store was lost'})
    (lost / custody.RUN_IDENTITY).write_text(json.dumps({'schema_version': 1, 'kind': 'run-identity',
                                                         'run_id': 'd' * 32, 'grants_authority': False}))
    assert init(lost, capsys)[0] == 2
    (lost / custody.RUN_IDENTITY).unlink()
    assert init(lost, capsys)[0] == 0 and bound_here(lost) != 'd' * 32


def test_two_initializations_of_copies_of_one_directory_admit_only_one(tmp_path, machine_rules, capsys):
    """Whichever location is initialized first is the run; the other is its copy."""
    first = prepared(tmp_path, 'first', {'request': 'one request'})
    second = tmp_path / 'second'
    shutil.copytree(first, second)
    assert init(second, capsys)[0] == 0
    code, err = init(first, capsys)
    assert code == 2 and str(second) in err
    assert journal(first) == []


@pytest.mark.parametrize('attempt', range(5))
def test_concurrent_initializations_of_two_copies_admit_exactly_one(tmp_path, machine_rules, attempt):
    import threading
    first = prepared(tmp_path, 'first', {'request': 'one request'})
    second = tmp_path / 'second'
    shutil.copytree(first, second)
    start, outcomes = threading.Barrier(2), {}

    def initialize(root):
        start.wait(10)
        try:
            gw.initialize_steering(root, route='operator')
            outcomes[root.name] = 'admitted'
        except custody.CustodyError as exc:
            outcomes[root.name] = str(exc)
    threads = [threading.Thread(target=initialize, args=(root,)) for root in (first, second)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)
    admitted = [name for name, outcome in outcomes.items() if outcome == 'admitted']
    assert len(outcomes) == 2 and len(admitted) == 1, outcomes
    refused = first if admitted == ['second'] else second
    assert 'renamed or copied run' in outcomes[refused.name] and journal(refused) == []


def test_qualification_directory_gets_its_journal_and_is_left_empty(tmp_path, machine_rules):
    """A qualification run that refuses before any process must leave nothing in its directory."""
    root = tmp_path / 'qualification'
    root.mkdir()
    gw.initialize_steering(root, route='transport-qualification')
    assert list(root.iterdir()) == []
    assert [record['route'] for record in journal(root)] == ['transport-qualification']
    assert gw.dispatch_permitted(root, None)[0]
