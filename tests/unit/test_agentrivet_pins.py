"""Census allowlist and no-subprocess guard; hashes only, no upstream source bodies.

Process events are exercised either through harmless commands (``true``) or by
raising the audit event directly, so a guard failure can never fork the test run.
"""
import os
from pathlib import Path
import subprocess
import sys
import threading
import pytest
from ravel.workflow import agentrivet_pins as pins


def rows(commit, table=None):
    files = (table or pins.ALLOWED)[commit]['files']
    return [{'path': p, 'sha256': s} for p, s in sorted(files.items())]


def test_tag_census_is_the_default_and_accepted():
    assert pins.DEFAULT_COMMIT.startswith('e4d12ec')
    assert pins.admit_census(rows(pins.DEFAULT_COMMIT)) == pins.DEFAULT_COMMIT


GATED = pins.COMPILE_GATED_COMMIT


def test_later_main_with_identical_core_and_roles_is_accepted():
    commit = 'cebc8e93a6c9cb48a23d07f5b2f6038613d260b7'
    assert pins.admit_census(rows(commit)) == commit
    tag, main = pins.ALLOWED[pins.DEFAULT_COMMIT]['files'], pins.ALLOWED[commit]['files']
    for key, name in pins.ROLE_FILES.items():
        if key != 'build':
            assert tag[name] == main[name]


def test_compile_gated_upstream_is_admitted_with_its_loop_features():
    assert pins.admit_census(rows(GATED)) == GATED
    assert pins.features(GATED) == {'compile_gate': True, 'analysis_id_in_prompts': True}
    assert pins.features(pins.DEFAULT_COMMIT) == {'compile_gate': False, 'analysis_id_in_prompts': False}
    assert 'agentrivet/build.py' in pins.ALLOWED[GATED]['files']
    with pytest.raises(pins.UpstreamCensusRefused, match='allowed AgentRivet'):
        pins.features('0' * 40)


def test_unknown_or_mixed_census_is_refused():
    mixed = rows(pins.DEFAULT_COMMIT)
    for row in mixed:
        if row['path'] == 'agentrivet/core.py':
            row['sha256'] = pins.ALLOWED[GATED]['files']['agentrivet/core.py']
    with pytest.raises(pins.UpstreamCensusRefused, match='agentrivet/core.py'):
        pins.admit_census(mixed)
    extra = rows(pins.DEFAULT_COMMIT) + [{'path': 'agentrivet/build.py', 'sha256': '0' * 64}]
    with pytest.raises(pins.UpstreamCensusRefused, match='allowed AgentRivet'):
        pins.admit_census(extra)
    wrong_doc = [dict(r, sha256='1' * 64) if r['path'] == 'README.md' else r for r in rows(pins.DEFAULT_COMMIT)]
    with pytest.raises(pins.UpstreamCensusRefused):
        pins.admit_census(wrong_doc)


def test_refused_table_still_names_a_known_incompatible_commit(monkeypatch):
    entry = {'label': 'synthetic incompatible tree', 'reason': 'its loop stores no drafts',
             'files': {'agentrivet/core.py': '2' * 64}}
    monkeypatch.setitem(pins.REFUSED, 'f' * 40, entry)
    with pytest.raises(pins.UpstreamCensusRefused, match='stores no drafts') as caught:
        pins.admit_census([{'path': 'agentrivet/core.py', 'sha256': '2' * 64}])
    assert 'e4d12ec' in str(caught.value) and '89903d0' in str(caught.value)


def test_member_pins_need_one_allowed_commit():
    files = pins.ALLOWED[pins.DEFAULT_COMMIT]['files']
    good = {k: {'path': '/x/' + v, 'sha256': files[v]} for k, v in pins.ROLE_FILES.items() if k != 'build'}
    assert pins.admit_member_pins(good) == [pins.DEFAULT_COMMIT, 'cebc8e93a6c9cb48a23d07f5b2f6038613d260b7']
    gated = pins.ALLOWED[GATED]['files']
    assert pins.admit_member_pins({k: {'path': '/x/' + v, 'sha256': gated[v]} for k, v in pins.ROLE_FILES.items()}) == [GATED]
    bad = dict(good, core={'path': '/x/core.py', 'sha256': gated['agentrivet/core.py']})
    with pytest.raises(pins.UpstreamCensusRefused, match='allowed AgentRivet'):
        pins.admit_member_pins(bad)


def test_guard_refuses_process_starts():
    with pytest.raises(pins.UpstreamExecutionRefused, match='subprocess.Popen'):
        with pins.no_subprocess('test'):
            subprocess.run(['true'], check=False)
    with pytest.raises(pins.UpstreamExecutionRefused, match='os.system'):
        with pins.no_subprocess('test'):
            os.system('true')
    for event in ('os.fork', 'os.posix_spawn', 'os.exec', 'os.forkpty'):
        with pytest.raises(pins.UpstreamExecutionRefused, match=event):
            with pins.no_subprocess('test'):
                sys.audit(event)          # the event alone; nothing is forked
    assert subprocess.run(['true'], check=False).returncode == 0   # inactive outside


def test_swallowed_refusal_is_raised_when_the_block_ends():
    with pytest.raises(pins.UpstreamExecutionRefused, match='subprocess.Popen'):
        with pins.no_subprocess('swallowing upstream'):
            try:
                subprocess.run(['true'], check=False)
            except Exception:
                pass


def test_guard_refuses_file_creation_in_cwd_only(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / 'sub').mkdir(); (tmp_path / 'existing.txt').write_text('read me')
    with pins.no_subprocess('files'):
        assert Path('existing.txt').read_text() == 'read me'
        (tmp_path / 'sub' / 'allowed.txt').write_text('outside the cwd itself')
    for action in (lambda: open('draft.cc', 'w'), lambda: os.open('draft.so', os.O_CREAT | os.O_WRONLY),
                   lambda: os.mkdir('scratch')):
        with pytest.raises(pins.UpstreamExecutionRefused, match='working directory'):
            with pins.no_subprocess('files'):
                action()
    assert not any(tmp_path.joinpath(n).exists() for n in ('draft.cc', 'draft.so', 'scratch'))


def test_guard_is_context_local_and_ravel_service_suspends_it():
    seen = []
    with pins.no_subprocess('outer'):
        def other():
            seen.append(pins.active())
        assert pins.active()
        with pins.ravel_service():
            assert not pins.active()
            worker = threading.Thread(target=other); worker.start(); worker.join()
            assert subprocess.run(['true'], check=False).returncode == 0
            with pins.ravel_service():
                pass
        assert pins.active()
    assert seen == [False] and not pins.active()


def test_upstream_call_inside_a_ravel_service_is_guarded_again():
    with pytest.raises(pins.UpstreamExecutionRefused, match='outer'):
        with pins.no_subprocess('outer'):
            with pins.ravel_service():
                with pytest.raises(pins.UpstreamExecutionRefused):
                    with pins.upstream_call():
                        subprocess.run(['true'], check=False)
    with pins.upstream_call():          # no suspended guard: a plain call
        assert not pins.active()


def test_thread_start_under_guard_is_refused():
    with pytest.raises(pins.UpstreamExecutionRefused, match='start_new_thread'):
        with pins.no_subprocess('threads'):
            threading.Thread(target=lambda: None).start()


def test_hook_installs_once():
    pins.install(); pins.install()
    assert pins._INSTALLED
