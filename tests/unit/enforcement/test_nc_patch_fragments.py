"""Execute complete proposed patch functions with inert collaborators.

These tests validate the proposal artifacts themselves. They neither install those
patches nor import the production CLI transport or contact an authority provider.
"""
from __future__ import annotations

import ast
import builtins
import hashlib
import os
from pathlib import Path
import shutil
import stat
from types import SimpleNamespace

import pytest


PATCHES = Path(__file__).resolve().parents[2] / 'fixtures' / 'enforcement' / 'patches'


def _added_function(filename, name):
    """Extract one contiguous, complete added function; context is never executed."""
    lines = (PATCHES / filename).read_text().splitlines()
    prefix = '+def ' + name + '('
    starts = [index for index, line in enumerate(lines) if line.startswith(prefix)]
    assert len(starts) == 1, (filename, name, starts)
    body = []
    for line in lines[starts[0]:]:
        if not line.startswith('+') or line.startswith('+++'):
            break
        value = line[1:]
        if body and value and not value[0].isspace() and value.startswith(('def ', 'class ', 'import ', 'from ')):
            break
        body.append(value)
    source = '\n'.join(body) + '\n'
    tree = ast.parse(source, filename=filename + ':' + name)
    assert len(tree.body) == 1 and isinstance(tree.body[0], ast.FunctionDef)
    function = tree.body[0]
    assert function.name == name
    assert isinstance(function.body[-1], ast.Return), 'patch extraction truncated the function tail'
    assert function.end_lineno == max(index for index, line in enumerate(body, 1) if line.strip())
    return tree


class _Refused(ValueError):
    pass


def _copy_function():
    def refuse(code, detail=None):
        raise _Refused(code)

    namespace = {'os': os, 'stat': stat, 'shutil': shutil,
                 'LaunchRefused': _Refused, '_refuse': refuse}
    exec(compile(_added_function('cli-home.patch', '_private_login_config'),
                 'cli-home.patch:_private_login_config', 'exec'), namespace)
    return namespace['_private_login_config']


def _digests(folder):
    return {p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in folder.rglob('*') if p.is_file() and not p.is_symlink()}


def test_cli_patch_copies_nested_login_privately_with_restrictive_modes(tmp_path):
    source = tmp_path / 'operator-login'
    nested = source / 'state' / 'account'
    nested.mkdir(parents=True)
    (source / 'credentials.json').write_bytes(b'{"fictional":"login token"}\n')
    (nested / 'refresh.token').write_bytes(b'fictional refresh credential\x00\xff')
    before = _digests(source)
    original_bytes = {name: (source / name).read_bytes() for name in before}
    previous_umask = os.umask(0o002)
    try:
        home = tmp_path / 'attempt.cli-home'
        config = _copy_function()(source, home)
    finally:
        os.umask(previous_umask)
    assert config == home / 'claude'
    assert _digests(config) == before
    assert _digests(source) == before
    for path in (home, config, *config.rglob('*')):
        expected = 0o700 if path.is_dir() else 0o600
        assert stat.S_IMODE(path.stat().st_mode) == expected, path
    (config / 'state' / 'account' / 'refresh.token').write_bytes(b'worker mutated only its private copy')
    assert (source / 'state' / 'account' / 'refresh.token').read_bytes() == original_bytes['state/account/refresh.token']
    assert _digests(source) == before


def test_cli_patch_rejects_symlink_and_cleans_partial_private_copy(tmp_path):
    source = tmp_path / 'operator-login'
    source.mkdir()
    (source / 'regular.token').write_bytes(b'fictional regular credential')
    outside = tmp_path / 'outside.token'
    outside.write_bytes(b'fictional outside credential')
    (source / 'linked.token').symlink_to(outside)
    before = _digests(source)
    home = tmp_path / 'refused.cli-home'
    with pytest.raises(_Refused, match='claude_config_dir:private-copy'):
        _copy_function()(source, home)
    assert not home.exists()
    assert (source / 'linked.token').is_symlink()
    assert _digests(source) == before
    assert outside.read_bytes() == b'fictional outside credential'
    # The same source with its unsafe entry removed is a usable control.
    (source / 'linked.token').unlink()
    config = _copy_function()(source, home)
    assert (config / 'regular.token').read_bytes() == b'fictional regular credential'
    assert _digests(config) == before


class _Modes:
    """An inert modes.admit contract consumer; it cannot create an authority record."""
    def __init__(self, *, resolve=False):
        self.calls = []
        self.resolve = resolve
        self.legacy_result = [{'code': 'unchanged-keyword-result'}]

    @staticmethod
    def _error(code, step, **detail):
        return {'code': code, 'step': step.get('id'), **detail}

    def admit(self, step, **kwargs):
        self.calls.append((step, kwargs))
        if not self.resolve:
            return self.legacy_result
        authority = kwargs['authority']
        pins = {'plan_sha256': kwargs['plan']['sha256']}
        try:
            record = authority('approve_plan', pins)
        except Exception as exc:
            return [self._error('mode_authority_unavailable', step, detail=str(exc))]
        if not record:
            return [self._error('mode_authority_missing', step)]
        return []


def _ml_function(modes, *, service=None):
    def inert_import(name, globals=None, locals=None, fromlist=(), level=0):
        assert name == '' and level == 3 and fromlist == ('authority',), (name, fromlist, level)
        if service is None:
            raise ImportError('inert authority service absent')
        return SimpleNamespace(authority=service)

    namespace = {'_modes': modes,
                 'governed': lambda step: step.get('operation') if step.get('operation') == 'published-classifier' else None,
                 '__builtins__': dict(vars(builtins), __import__=inert_import)}
    exec(compile(_added_function('ml-route-admit.patch', 'admit'), 'ml-route-admit.patch:admit', 'exec'), namespace)
    return namespace['admit']


STEP = {'id': 'inference', 'operation': 'published-classifier'}
PLAN = {'sha256': 'fictional-plan-sha', 'steps': [STEP]}


def test_ml_patch_retains_legacy_keyword_call_without_wrapping_authority():
    modes = _Modes()
    admit = _ml_function(modes)
    callback = lambda kind, pins: None
    signature_table, executors = {}, {'operations': {}}
    result = admit(STEP, plan=PLAN, authority=callback, signature_table=signature_table, executors=executors)
    assert result is modes.legacy_result
    assert modes.calls == [(STEP, {'plan': PLAN, 'authority': callback,
                                  'signature_table': signature_table, 'executors': executors})]
    assert modes.calls[0][1]['authority'] is callback
    assert modes.calls[0][1]['plan'] is PLAN


def test_ml_patch_forwards_all_plan_and_context_scope_pins_to_explicit_authority():
    modes = _Modes(resolve=True)
    admit = _ml_function(modes)
    observed = []

    def authority(kind, pins):
        assert kind == 'approve_plan'
        assert pins == {'plan_sha256': 'fictional-plan-sha', 'reading_sha256': 'reading-pin',
                        'contract_sha256': 'contract-pin'}
        observed.append((kind, dict(pins)))
        return {'kind': kind, 'pins': dict(pins)}

    context = {'plan': PLAN, 'authority': authority, 'pins': {'reading_sha256': 'reading-pin'},
               'scope_pins': {'contract_sha256': 'contract-pin'}}
    assert admit(STEP, context) == []
    assert len(observed) == 1
    assert len(modes.calls) == 1
    assert modes.calls[0][1]['plan'] is PLAN
    assert context['pins'] == {'reading_sha256': 'reading-pin'}
    assert context['scope_pins'] == {'contract_sha256': 'contract-pin'}


def test_ml_patch_missing_authority_and_store_holds_without_synthesizing_a_record():
    modes = _Modes(resolve=True)
    admit = _ml_function(modes)
    result = admit(STEP, {'plan': PLAN})
    assert [row['code'] for row in result] == ['mode_authority_unavailable']
    assert modes.calls == []
    # A callable returning no record must remain a hold rather than becoming approval.
    observed = []

    def absent(kind, pins):
        observed.append((kind, dict(pins)))
        return None

    result = admit(STEP, {'plan': PLAN, 'authority': absent})
    assert [row['code'] for row in result] == ['mode_authority_missing']
    assert observed == [('approve_plan', {'plan_sha256': 'fictional-plan-sha'})]


def test_ml_patch_refuses_conflicting_context_and_plan_scope_without_authority_call():
    modes = _Modes(resolve=True)
    admit = _ml_function(modes)
    observed = []

    def authority(kind, pins):
        observed.append((kind, pins))
        return {'kind': kind}

    context = {'plan': PLAN, 'authority': authority,
               'pins': {'input_sha256': 'first'}, 'scope_pins': {'input_sha256': 'second'}}
    assert [row['code'] for row in admit(STEP, context)] == ['mode_authority_unavailable']
    assert modes.calls == [] and observed == []
    context = {'plan': PLAN, 'authority': authority, 'scope_pins': {'plan_sha256': 'stale-plan'}}
    assert [row['code'] for row in admit(STEP, context)] == ['mode_authority_unavailable']
    assert observed == []


def test_ml_patch_unknown_mode_is_noop_without_accessing_authority():
    modes = _Modes(resolve=True)
    admit = _ml_function(modes)
    assert admit({'id': 'ordinary', 'operation': 'ordinary-calculation'}, {'plan': None}) == []
    assert modes.calls == []


def test_ml_patch_store_lookup_forwards_exact_scope_and_only_reads_current_authority():
    modes = _Modes(resolve=True)
    observed = []
    store = object()

    def current(observed_store, kind, pins):
        assert observed_store is store
        observed.append((kind, dict(pins)))
        return {'kind': kind, 'pins': dict(pins)}

    # This service exposes no request/issue method: a synthesized record cannot be obtained from it.
    admit = _ml_function(modes, service=SimpleNamespace(current=current))
    assert admit(STEP, {'plan': PLAN, 'store': store, 'scope_pins': {'input_sha256': 'input-pin'}}) == []
    assert observed == [('approve_plan', {'input_sha256': 'input-pin', 'plan_sha256': 'fictional-plan-sha'})]
