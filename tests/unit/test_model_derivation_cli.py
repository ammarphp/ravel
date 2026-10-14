"""Public routing and help must preserve the derivation module's authority."""
import os
from pathlib import Path
import subprocess
import sys

import pytest
from ravel import cli
from ravel.physics import model_derivation_bridge as bridge

@pytest.mark.parametrize('arguments', [
    ['plan','--help'], ['handoff','--help'],
])
def test_focused_route_forwards_exact_arguments_and_return_code(monkeypatch, arguments):
    calls=[]
    monkeypatch.setattr(bridge,'main',lambda argv: calls.append(argv) or 23)
    assert cli.main(['model-derivation-bridge',*arguments]) == 23
    assert calls == [arguments]

def test_public_top_level_help_lists_derivation_without_calling_it(monkeypatch,capsys):
    monkeypatch.setattr(bridge,'main',lambda argv: pytest.fail('help dispatched derivation'))
    with pytest.raises(SystemExit) as result: cli.main(['--help'])
    assert result.value.code == 0
    assert 'model-derivation-bridge' in capsys.readouterr().out

@pytest.mark.parametrize('subcommand,required', [
    ('plan','--provider-readiness-run'), ('handoff','--rundir'),
])
def test_public_focused_help_uses_original_parser(monkeypatch,capsys,subcommand,required):
    monkeypatch.setattr(bridge,'prepare',lambda args: pytest.fail('help prepared model'))
    monkeypatch.setattr(bridge,'qualified_handoff',lambda *args: pytest.fail('help qualified output'))
    with pytest.raises(SystemExit) as result: cli.main(['model-derivation-bridge',subcommand,'--help'])
    assert result.value.code == 0
    assert required in capsys.readouterr().out

def test_incomplete_plan_refuses_before_prepare(monkeypatch):
    monkeypatch.setattr(bridge,'prepare',lambda args: pytest.fail('incomplete plan dispatched'))
    with pytest.raises(SystemExit) as result: cli.main(['model-derivation-bridge','plan'])
    assert result.value.code == 2

def test_focused_route_keeps_original_reuse_refusal(monkeypatch,capsys):
    def refused(*args): raise ValueError('actual accepted model_source_derivation review required for handoff')
    monkeypatch.setattr(bridge,'qualified_handoff',refused)
    assert cli.main(['model-derivation-bridge','handoff','--rundir','old','--out','new']) == 2
    assert 'actual accepted model_source_derivation' in capsys.readouterr().err

def test_direct_module_help_has_real_entrypoint_without_preparing(tmp_path):
    env={**os.environ,'PYTHONPATH':str(Path(bridge.__file__).resolve().parents[2]),'PYTHONDONTWRITEBYTECODE':'1','PYTHONNOUSERSITE':'1'}
    result=subprocess.run([sys.executable,'-B','-m','ravel.physics.model_derivation_bridge','plan','--help'],cwd=tmp_path,env=env,capture_output=True,text=True,timeout=15)
    assert result.returncode == 0, result.stderr
    assert '--provider-readiness-run' in result.stdout and '--trust-model-source' in result.stdout
    assert not tuple(tmp_path.iterdir())
