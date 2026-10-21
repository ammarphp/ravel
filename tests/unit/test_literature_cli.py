"""Inert routing controls and original-parser output parity."""
import sys

import pytest

from ravel.workflow import literature, literature_cli, literature_serving


@pytest.fixture
def routed(monkeypatch):
    calls = []
    result = object()

    def legacy_main(argv):
        calls.append(('legacy', argv, None))
        return result

    def serving_main(argv, *, serving=None):
        calls.append(('serving', argv, serving))
        return result

    monkeypatch.setattr(literature, 'main', legacy_main)
    monkeypatch.setattr(literature_serving, 'main', serving_main)
    return calls, result


@pytest.mark.parametrize('command', [
    'search', 'get-paper', 'list-papers', 'compare-measurements', 'replay', 'audit',
])
@pytest.mark.parametrize('trust', [False, True])
def test_serving_routes_preserve_arguments_and_trust(routed, command, trust):
    calls, result = routed
    argv = [command, '--request', 'fictional.json', '--help']
    serving = object() if trust else None

    assert literature_cli.main(argv, serving=serving) is result

    assert len(calls) == 1
    assert calls[0][0] == 'serving'
    assert calls[0][1] is argv
    assert calls[0][2] is serving


def test_locate_alias_changes_only_command(routed):
    calls, result = routed
    argv = ['locate', '--request', 'fictional.json', '--rundir', 'fictional-run']
    original = list(argv)
    serving = object()

    assert literature_cli.main(argv, serving=serving) is result

    assert calls == [('serving', ['get-paper', *original[1:]], serving)]
    assert argv == original


@pytest.mark.parametrize('argv', [
    [], ['--help'], ['-h'], ['check-cards'], ['follow'], ['resolve-title'], ['tier'],
    ['unknown'], ['advanced-operation'], ['--help', 'search'],
    ['follow', 'search', '--request', 'fictional.json'],
])
def test_legacy_routes_preserve_argument_identity_without_trust(routed, argv):
    calls, result = routed

    assert literature_cli.main(argv, serving=object()) is result

    assert len(calls) == 1
    assert calls[0][0] == 'legacy'
    assert calls[0][1] is argv
    assert calls[0][2] is None


@pytest.mark.parametrize('arguments, owner, expected', [
    (['search', '--help'], 'serving', ['search', '--help']),
    (['locate', '--help'], 'serving', ['get-paper', '--help']),
    (['--help'], 'legacy', ['--help']),
    ([], 'legacy', []),
])
def test_default_arguments_use_process_arguments(routed, monkeypatch, arguments, owner, expected):
    calls, result = routed
    process_argv = ['fictional-cli', *arguments]
    monkeypatch.setattr(sys, 'argv', process_argv)
    serving = object()

    assert literature_cli.main(serving=serving) is result

    assert calls == [(owner, expected, serving if owner == 'serving' else None)]
    assert sys.argv == ['fictional-cli', *arguments]


def test_explicit_empty_arguments_override_process_arguments(routed, monkeypatch):
    calls, result = routed
    monkeypatch.setattr(sys, 'argv', ['fictional-cli', 'search'])
    argv = []

    assert literature_cli.main(argv) is result

    assert calls == [('legacy', [], None)]
    assert calls[0][1] is argv


@pytest.mark.parametrize('argv, code', [
    (['--help'], 0), (['-h'], 0), ([], 2), (['check-cards'], 2),
    (['follow'], 2), (['resolve-title'], 2),
])
def test_original_parser_output_bytes_are_preserved(capsys, monkeypatch, argv, code):
    monkeypatch.setattr(sys, 'argv', ['fictional-cli'])

    with pytest.raises(SystemExit) as direct:
        literature.main(argv)
    direct_output = capsys.readouterr()

    with pytest.raises(SystemExit) as facade:
        literature_cli.main(argv, serving=object())
    facade_output = capsys.readouterr()

    assert direct.value.code == facade.value.code == code
    assert facade_output.out.encode('utf-8') == direct_output.out.encode('utf-8')
    assert facade_output.err.encode('utf-8') == direct_output.err.encode('utf-8')
